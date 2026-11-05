"""Check instrument balloons: tags, attachment, placement and signal lines."""

import math
import warnings
from collections.abc import Callable

import pytest

from pandid import Flowsheet, units as U
from pandid.portgeom import port_point
from pandid.streams import Stream

from _layout_cases import frame_of


def _line(**kw):
    """Return a level run through a control valve pinned by its nozzle, with FT-101 on it."""
    fs = Flowsheet("tap")
    feed = fs.add(U.Feed("Feed")).pin(x=110, y=195)
    fv = fs.add(U.Valve("FV-101", variant="control"))
    fv.pin(x=300, port="inlet", y=195)  # the run is at y=195
    prod = fs.add(U.Product("Product")).pin(x=520, y=195)
    s = fs.connect(feed.outlet, fv.inlet)
    fs.connect(fv.outlet, prod.inlet)
    inst = fs.add_instrument("FT", 101, sensing=s, **kw)
    fs.route()
    return fs, s, inst, fv


def _hatch_marks(svg: str) -> int:
    """Count the cross-hatch strokes drawn on pneumatic signal lines."""
    body = svg.split('<g id="streams">', 1)[1].split("</g>", 1)[0]
    return body.count("<line ")


def test_instrument_tag_rendered_inside():
    fs = Flowsheet("i")
    a = fs.add(U.Instrument("FT-101"))
    b = fs.add(U.Instrument("FIC-101", display="central"))
    fs.connect(a.sig_out, b.sig_in, kind="electric")
    svg = fs.to_svg()
    assert ">FT<" in svg and ">101<" in svg  # split tag drawn inside
    assert 'stroke-dasharray="7,4"' in svg  # electric signal dashed


def test_signal_kinds_accepted():
    for k in ("electric", "pneumatic", "data", "capillary", "software"):
        fs = Flowsheet("k")
        a = fs.add(U.Instrument("A-1"))
        b = fs.add(U.Instrument("B-1"))
        fs.connect(a.sig_out, b.sig_in, kind=k)  # must not raise


def test_signal_feedback_loop_lays_out():
    # A control loop's signal feedback must not break layering.
    fs = Flowsheet("loop")
    a = fs.add(U.Instrument("T-1"))
    b = fs.add(U.Instrument("C-1"))
    fs.connect(a.sig_out, b.sig_in, kind="electric")
    fs.connect(b.sig_out, a.pv, kind="pneumatic")  # feedback
    fs.layout()  # must not raise "Cycle detected"


def test_instrument_tag_split_alphanumeric():
    fs = Flowsheet("i")
    a = fs.add(U.Instrument("PT101A"))
    b = fs.add(U.Instrument("X"))
    fs.connect(a.sig_out, b.sig_in, kind="electric")
    svg = fs.to_svg()
    assert ">PT<" in svg and ">101A<" in svg  # letters over full loop suffix


# --- tag ---------------------------------------------------------------------


def test_combined_tag_still_accepted():
    for tag, expect in (("FT-101", ("FT", "101")), ("PT101A", ("PT", "101A")), ("X", ("X", ""))):
        inst = U.Instrument(tag)
        assert (inst.type, inst.number) == expect


def test_the_three_spellings_of_one_tag_are_one_instrument():
    """Check that ``FT, 101``, ``FT-101`` and ``FT101`` name and tag one instrument alike."""
    built = [U.Instrument("FT", 101), U.Instrument("FT-101"), U.Instrument("FT101")]
    assert {(i.name, i.tag, i.type, i.number) for i in built} == {("FT-101", "FT-101", "FT", "101")}


def test_a_tag_that_is_all_letters_or_all_digits_keeps_itself():
    """Check that an all-letter or all-digit tag is kept without a hyphen."""
    assert U.Instrument("X").name == "X"
    assert U.Instrument("101").name == "101"


@pytest.mark.parametrize("spelling", [("FT", 101), ("FT-101",), ("FT101",)])
def test_an_instrument_comes_back_from_the_spec_under_the_tag_it_went_out_with(spelling):
    """Check that a spec round trip keeps an instrument's name and tag."""
    fs = Flowsheet("s")
    inst = fs.add(U.Instrument(*spelling))
    (rebuilt,) = Flowsheet.from_dict(fs.to_dict()).units
    assert (rebuilt.name, rebuilt.tag) == (inst.name, inst.tag) == ("FT-101", "FT-101")


def test_balloon_draws_bare_number_not_the_whole_tag():
    fs = Flowsheet("i")
    fs.add_instrument("FT", 303)
    svg = fs.to_svg()
    assert ">FT<" in svg and ">303<" in svg
    assert ">FT-303<" not in svg


def test_interlock_square_carries_only_its_number():
    fs = Flowsheet("i")
    fs.add_instrument("I", 2, variant="logic")
    svg = fs.to_svg()
    assert ">2<" in svg and ">I<" not in svg


@pytest.mark.parametrize("variant", ["sis", "interlock"])
def test_a_diamond_with_no_number_letters_in_capitals_in_both_backends(variant):
    """Check that a numberless diamond writes its letters in capitals in SVG and draw.io."""
    fs = Flowsheet("i")
    fs.add(U.Instrument("is", variant=variant))
    assert ">IS</text>" in fs.to_svg()
    assert 'value="IS"' in fs.to_drawio()


def test_the_two_trip_squares_are_the_two_isa_symbols_they_claim_to_be():
    """Check that the SIS symbol is a diamond in a square and the interlock a plain diamond."""
    from pandid.render.symbols import default_registry

    sis = default_registry.get("instrument", "sis")
    interlock = default_registry.get("instrument", "interlock")
    assert "<rect" in sis.svg and "<polygon" in sis.svg
    assert "<rect" not in interlock.svg and "<polygon" in interlock.svg
    # The diamond is the same diamond: vertices on the midpoints of a 40 box.
    for sym in (sis, interlock):
        assert 'points="20,1 39,20 20,39 1,20"' in sym.svg
        assert (sym.width, sym.height) == (40.0, 40.0)


def test_logic_is_a_second_name_for_the_sis_square():
    """Check that ``logic`` draws the same artwork as ``sis``."""
    from pandid.render.symbols import default_registry

    assert default_registry.get("instrument", "sis") is default_registry.get("instrument", "logic")
    svgs = set()
    for variant in ("sis", "logic"):
        fs = Flowsheet("i")
        fs.add(U.Instrument("I", 1, variant=variant)).pin(x=40, y=40)
        # the <defs> id follows the spelling; the geometry inside it must not
        svgs.add(fs.to_svg().replace(f"sym_instrument_{variant}", "ID"))
    assert len(svgs) == 1


@pytest.mark.parametrize("variant", ["sis", "logic", "interlock"])
def test_every_trip_square_repeats_wherever_its_logic_acts(variant):
    """Check that a trip square's tag may be drawn at several places on one sheet."""
    fs = Flowsheet("i")
    squares = [fs.add_instrument("I", 1, variant=variant) for _ in range(3)]
    assert [s.tag for s in squares] == ["I-1"] * 3
    assert len({s.name for s in squares}) == 3


@pytest.mark.parametrize(
    "tag, variants",
    [
        (("I", 1), ("sis", "interlock")),
        (("LT", 101), ("default", "default")),
        (("I", 1), ("logic", "default")),
        (("I", 1), ("default", "logic")),
    ],
    ids=["diamond-and-square", "two-transmitters", "square-then-balloon", "balloon-then-square"],
)
def test_two_symbols_may_not_share_a_tag(tag, variants):
    """Check that a second instrument on a tag already used is refused."""
    first, second = variants
    fs = Flowsheet("i")
    fs.add(U.Instrument(*tag, variant=first))
    with pytest.raises(ValueError, match="already exists on this flowsheet"):
        fs.add(U.Instrument(*tag, variant=second))


# --- attachment to a stream --------------------------------------------------


def test_attached_to_stream_sits_on_the_routed_path():
    fs, s, ft, _ = _line(at=0.6, offset=45)
    pts = s.route.waypoints
    y = pts[0][1]
    x0, x1 = pts[0][0], pts[-1][0]
    assert ft.tap == pytest.approx((x0 + 0.6 * (x1 - x0), y))
    # default angle 90 = perpendicular to the flow, on the upstream-left side
    assert ft.frame.cx == pytest.approx(ft.tap[0])
    assert ft.frame.cy == pytest.approx(y - 45)


def test_offset_zero_leaves_the_element_on_the_line():
    fs, s, fe, _ = _line(at=0.5, offset=0)
    assert (fe.frame.cx, fe.frame.cy) == pytest.approx(fe.tap)
    # nothing to draw an impulse line to, and the line it straddles stays straight
    assert '<g id="instrument_taps">' not in fs.to_svg()
    assert {p[1] for p in s.route.waypoints} == {fe.tap[1]}


def test_angle_is_measured_from_the_flow_direction():
    _, _, up, _ = _line(offset=60, angle=90)
    _, _, down, _ = _line(offset=60, angle=-90)
    _, _, ahead, _ = _line(offset=60, angle=0)
    assert up.frame.cy == pytest.approx(up.tap[1] - 60)  # counter-clockwise: above
    assert down.frame.cy == pytest.approx(down.tap[1] + 60)  # clockwise: below
    assert ahead.frame.cx == pytest.approx(ahead.tap[0] + 60)  # along the flow
    assert ahead.frame.cy == pytest.approx(ahead.tap[1])


def test_an_attached_balloon_keeps_off_another_units_tag():
    """Check that sheet 16 draws LT-203 clear of M-201's tag, and no balloon on another's tag."""
    from _render_cases import gallery
    from pandid.layout.attach import _tag_boxes, on_a_tag
    from pandid.layout.conflicts import boxes_overlap
    from pandid.portgeom import unit_box

    fs, _ = gallery.flowsheet("16_stirred_reactor_train")
    fs.route()
    lt = next(u for u in fs.units if u.name == "LT-203")
    tag = next(box for owner, box in _tag_boxes(fs) if owner.name == "M-201")
    assert not boxes_overlap(unit_box(lt, frame_of(lt)), tag)
    assert not on_a_tag(fs)


def test_a_balloon_kept_off_a_tag_does_not_cross_a_line_to_get_there():
    """Check that clearing a mixer's tag does not move TT-1 so its tap crosses the run above."""
    from pandid.render.svg import tap_lines, tap_route
    from pandid.route_geometry import stream_polyline
    from pandid.routing.metrics import crossing_count

    fs = Flowsheet("tap crossing")
    feed, product = fs.add(U.Feed("F-1")).pin(x=100, y=400), fs.add(U.Product("P-1"))
    lower = fs.connect(feed.outlet, product.pin(x=600, y=400).inlet)
    upper = fs.add(U.Feed("F-2")).pin(x=100, y=330)
    mixer = fs.add(U.Fitting("M-101", variant="static_mixer", label_pos="bottom"))
    mixer.pin(port="inlet", x=325, y=330)
    fs.connect(upper.outlet, mixer.inlet)
    fs.connect(mixer.outlet, fs.add(U.Product("P-2")).pin(x=600, y=330).inlet)
    fs.add_instrument("TT", 1, sensing=lower, at=0.4, offset=50, angle=45)
    fs.route()
    lines = [stream_polyline(s) for s in fs.streams]
    taps = [tap_route(u, tap, centre) for u, tap, centre in tap_lines(fs)]
    assert taps
    assert crossing_count(lines + taps) == 0


def test_a_balloon_kept_off_a_tag_is_not_moved_under_other_text():
    """Check that clearing a mixer's tag does not move TT-1 under HV-2's NC plate."""
    import re

    from pandid.layout.conflicts import boxes_overlap
    from pandid.portgeom import unit_box

    fs = Flowsheet("NC overlap")
    feed, product = fs.add(U.Feed("F-1")).pin(x=100, y=400), fs.add(U.Product("P-1"))
    lower = fs.connect(feed.outlet, product.pin(x=600, y=400).inlet)
    valve = fs.add(
        U.Valve("HV-2", variant="butterfly", normal_position="closed", label_pos="bottom")
    ).pin(x=230, y=316)
    mixer = fs.add(U.Fitting("M-101", variant="static_mixer", label_pos="bottom"))
    mixer.pin(port="inlet", x=325, y=320)
    upper = fs.add(U.Feed("F-2")).pin(x=100, y=323.5)
    fs.connect(upper.outlet, valve.inlet)
    fs.connect(valve.outlet, mixer.inlet)
    fs.connect(mixer.outlet, fs.add(U.Product("P-2")).pin(x=600, y=250).inlet)
    tt = fs.add_instrument("TT", 1, near=lower, at=0.4, offset=50, angle=45)
    body = fs.to_svg(diagram="p&id").split("</defs>", 1)[1]
    nc = re.search(r'<text x="([\d.]+)" y="([\d.]+)"[^>]*>NC</text>', body)
    assert nc is not None
    x, y = float(nc.group(1)), float(nc.group(2))
    plates = [
        (float(m[0]), float(m[1]), float(m[0]) + float(m[2]), float(m[1]) + float(m[3]))
        for m in re.findall(
            r'<rect x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" height="([\d.]+)" '
            r'fill="white" />',
            body,
        )
    ]
    under_nc = [p for p in plates if p[0] <= x <= p[2] and p[1] <= y <= p[3]]
    assert under_nc
    assert not any(boxes_overlap(unit_box(tt, frame_of(tt)), p) for p in under_nc)


def test_angle_follows_a_reroute_rather_than_the_screen():
    """Check that the angle is measured from the flow on a vertical leg, not the screen."""
    fs = Flowsheet("v")
    feed = fs.add(U.Feed("Feed")).pin(x=60, y=60)
    col = fs.add(U.Column("T-1")).pin(x=300, y=300)
    s = fs.connect(feed.outlet, col.feed)
    # Mid-run, and measured on the dog-leg's vertical leg, which is the
    # only part of this route the question is even about. Taken hard
    # against the nozzle instead (``at=0.99``) the tap sits 6px off T-1
    # and a 44px bubble perpendicular to it lands *inside* the column
    # whatever the offset, so `place_attached` stands it off and there is
    # no perpendicular left to assert.
    inst = fs.add_instrument("PT", 1, sensing=s, at=0.5, offset=40)
    fs.route()
    pts = list(s.route.waypoints)
    leg = next((a, b) for a, b in zip(pts, pts[1:]) if a[0] == b[0])
    ux, uy = leg[1][0] - leg[0][0], leg[1][1] - leg[0][1]
    n = math.hypot(ux, uy)
    assert _tap_of(inst)[0] == pytest.approx(leg[0][0])  # the tap is on that leg
    # 90 CCW of the flow direction, on a y-down canvas
    assert (inst.frame.cx - inst.tap[0]) == pytest.approx(40 * uy / n, abs=1e-6)
    assert (inst.frame.cy - inst.tap[1]) == pytest.approx(-40 * ux / n, abs=1e-6)


def test_impulse_line_is_drawn_thin_from_the_tap():
    fs, _, ft, _ = _line(at=0.5, offset=60)
    svg = fs.to_svg()
    assert '<g id="instrument_taps">' in svg
    assert f'x1="{ft.tap[0]:g}" y1="{ft.tap[1]:g}"' in svg
    assert 'stroke-width="1"' in svg


# --- attachment to a unit ----------------------------------------------------


def test_attached_to_unit_hangs_off_the_named_face():
    fs = Flowsheet("u")
    drum = fs.add(U.Vessel("V-101")).pin(x=200, y=100)
    lic = fs.add_instrument("LIC", 101, sensing=drum, face="E", offset=80, display="central")
    fs.route()
    f = drum.frame
    assert lic.tap == pytest.approx((f.x_max, f.cy))
    assert (lic.frame.cx, lic.frame.cy) == pytest.approx((f.x_max + 80, f.cy))


def test_stream_host_rejects_a_face():
    fs = Flowsheet("s")
    feed = fs.add(U.Feed("F"))
    prod = fs.add(U.Product("P"))
    s = fs.connect(feed.outlet, prod.inlet)
    with pytest.raises(ValueError):
        fs.add_instrument("FT", 1, sensing=s, at="E")
    with pytest.raises(ValueError):
        fs.add_instrument("FT", 2, sensing=s, at=1.4)


def test_a_balloon_refused_its_placement_never_reaches_the_sheet():
    """Check that a balloon refused its placement is not added and its tag stays free."""
    fs = Flowsheet("atomic")
    drum = fs.add(U.Vessel("V-101")).pin(x=200, y=100)
    before = list(fs.units)

    with pytest.raises(ValueError, match="face= is a side of V-101"):
        fs.add_instrument("LT", 101, sensing=drum, face="up")

    assert list(fs.units) == before
    assert fs.add_instrument("LT", 101, sensing=drum, face="N").name == "LT-101"


def test_a_balloon_may_not_be_anchored_to_another_sheets_unit():
    """Check that a balloon anchored to another sheet's unit is refused and not added."""
    fs = Flowsheet("host")
    drum = fs.add(U.Vessel("V-101")).pin(x=200, y=100)
    elsewhere = Flowsheet("owner")
    theirs = elsewhere.add(U.Vessel("V-201")).pin(x=200, y=100)
    before = list(fs.units)

    with pytest.raises(ValueError, match=r"sensing='V-201' is on flowsheet 'owner'"):
        fs.add_instrument("LT", 101, sensing=theirs)

    assert list(fs.units) == before
    assert fs.add_instrument("LT", 101, sensing=drum).name == "LT-101"


# --- face= names a side of a unit, at= a fraction along a line ---------------


def _hosts() -> tuple[Flowsheet, U.Vessel, U.Fitting, Stream]:
    """Return a line into a tagged venturi and on to a drum: one host of each kind."""
    fs = Flowsheet("face")
    feed = fs.add(U.Feed("Feed"))
    fe = fs.add(U.Fitting("FE-303", variant="venturi"))
    drum = fs.add(U.Vessel("V-101"))
    line = fs.connect(feed.outlet, fe.inlet)
    fs.connect(fe.outlet, drum.inlet)
    return fs, drum, fe, line


def _placement(fs: Flowsheet) -> list[tuple[object, ...]]:
    """Return each unit's name, host, fraction, face and balloon."""
    return [
        (u.name, vars(u).get("host"), vars(u).get("at"), vars(u).get("face"), u.balloon)
        for u in fs.units
    ]


def test_face_names_the_side_of_a_unit_and_defaults_to_east():
    fs, drum, _, _ = _hosts()
    assert fs.add_instrument("LT", 1, sensing=drum).face == "E"
    north = fs.add_instrument("LT", 2, sensing=drum, face="N")
    assert (north.at, north.face) == (None, "N")
    # nozzle()'s spellings, stored as the compass letter.
    assert fs.add_instrument("LT", 3, sensing=drum, face="top").face == "N"
    assert fs.add_instrument("LT", 4, sensing=drum, face=" w ").face == "W"


def test_a_balloon_on_a_flag_taps_the_pennant_it_draws():
    """Check that a balloon on a feed flag taps its pennant, unfaced or on its top."""
    from pandid.render.svg import boundary_flag

    fs = Flowsheet("feed pressure")
    feed, pump, out = fs.add(U.Feed("Feed")), fs.add(U.Pump("P-101")), fs.add(U.Product("Out"))
    fs.connect(feed.outlet, pump.suction)
    fs.connect(pump.discharge, out.inlet)
    unfaced = fs.add_instrument("PI", 101, sensing=feed)
    north = fs.add_instrument("PI", 102, sensing=feed, face="N")
    fs.route()
    assert feed.frame is not None
    x0, y0, x1, y1 = boundary_flag(feed, feed.frame).box
    assert unfaced.tap == (x1, (y0 + y1) / 2)
    assert north.tap == ((x0 + x1) / 2, y0)


def test_a_balloon_on_a_line_has_a_fraction_and_no_face():
    fs, _, _, line = _hosts()
    ft = fs.add_instrument("FT", 1, sensing=line, at=0.3)
    assert (ft.at, ft.face) == (0.3, None)
    assert fs.add_instrument("FT", 2, sensing=line).at == 0.5


_AT_A_FACE = {
    "add_instrument": lambda fs, drum, fe: fs.add_instrument("LT", 101, sensing=drum, at="N"),
    "add_balloon": lambda fs, drum, fe: fs.add_balloon(fe, at="N"),
    "attach": lambda fs, drum, fe: fs.add(U.Instrument("LT", 101)).attach(drum, at="N"),
}


@pytest.mark.parametrize("entry", sorted(_AT_A_FACE))
def test_a_face_given_as_at_warns_at_the_authors_line(entry: str, same_file):
    """Check that ``at=`` given a face warns once, at the caller's line, and places by face."""
    fs, drum, fe, _ = _hosts()
    with pytest.warns(DeprecationWarning, match="use face='N'") as caught:
        inst = _AT_A_FACE[entry](fs, drum, fe)
    assert len(caught) == 1
    assert same_file(caught[0].filename) == same_file(__file__)
    assert (inst.at, inst.face) == (None, "N")
    found = [i.message for i in fs.validate() if i.code == "deprecated"]
    assert found == [str(caught[0].message)]
    assert found[0].startswith(f"{inst.name}: ")


def test_a_face_given_as_at_is_placed_where_face_puts_it():
    old, old_drum, _, _ = _hosts()
    with pytest.warns(DeprecationWarning):
        old_lt = old.add_instrument("LT", 101, sensing=old_drum, at="N", offset=60)
    new, new_drum, _, _ = _hosts()
    new_lt = new.add_instrument("LT", 101, sensing=new_drum, face="N", offset=60)
    old.route()
    new.route()
    assert new_drum.frame is not None and new_lt.tap is not None
    assert new_lt.tap[1] == pytest.approx(new_drum.frame.y)
    assert old_lt.tap == new_lt.tap
    assert old.to_svg() == new.to_svg()


_REFUSED = {
    "both on a unit": (
        lambda fs, lt, drum, fe, line: fs.add_instrument("LT", 1, sensing=drum, at="N", face="N"),
        "V-101 is a unit, so give face= alone",
    ),
    "both on a line": (
        lambda fs, lt, drum, fe, line: fs.add_instrument("FT", 1, sensing=line, at=0.5, face="N"),
        "is a line, so give at= alone",
    ),
    "both on a balloon's element": (
        lambda fs, lt, drum, fe, line: fs.add_balloon(fe, at="N", face="N"),
        "FE-303 is a unit, so give face= alone",
    ),
    "both on attach": (
        lambda fs, lt, drum, fe, line: lt.attach(drum, at="N", face="N"),
        "V-101 is a unit, so give face= alone",
    ),
    "face on a line": (
        lambda fs, lt, drum, fe, line: fs.add_instrument("FT", 1, sensing=line, face="N"),
        "is a line; give at=",
    ),
    "face on attach to a line": (
        lambda fs, lt, drum, fe, line: lt.attach(line, face="N"),
        "is a line; give at=",
    ),
    "an old face on a taken tag": (
        lambda fs, lt, drum, fe, line: fs.add_instrument("LT", 100, sensing=drum, at="S"),
        "already exists",
    ),
    "at and face with no host": (
        lambda fs, lt, drum, fe, line: fs.add_instrument("LT", 1, at="S", face="N"),
        "no host for at= or face= to place the balloon on; give sensing=, acting_on= or near=",
    ),
    "face with no host": (
        lambda fs, lt, drum, fe, line: fs.add_instrument("LT", 1, face="N"),
        "no host for face=",
    ),
    "a fraction with no host": (
        lambda fs, lt, drum, fe, line: fs.add_instrument("LT", 1, at=0.5),
        "no host for at=",
    ),
    "an old face with no host": (
        lambda fs, lt, drum, fe, line: fs.add_instrument("LT", 1, at="S"),
        "no host for at=",
    ),
}


@pytest.mark.parametrize("case", sorted(_REFUSED))
def test_a_refused_face_leaves_the_sheet_unchanged_and_warns_nothing(case: str):
    fs, drum, fe, line = _hosts()
    lt = fs.add_instrument("LT", 100, sensing=drum, face="W")
    before = _placement(fs)
    call, match = _REFUSED[case]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises(ValueError, match=match):
            call(fs, lt, drum, fe, line)
    assert caught == []
    assert _placement(fs) == before


def test_a_fraction_on_a_unit_names_face():
    fs, drum, _, _ = _hosts()
    with pytest.raises(ValueError, match="V-101 is a unit; give face="):
        fs.add_instrument("LT", 1, sensing=drum, at=0.5)


_BAD_ATTACH = {
    "a bad angle": lambda lt, drum, line: lt.attach(drum, face="S", angle="bad"),
    "a bad angle on a line": lambda lt, drum, line: lt.attach(line, at=0.3, angle="bad"),
    "a bad offset": lambda lt, drum, line: lt.attach(drum, face="S", offset="bad"),
    "a negative offset": lambda lt, drum, line: lt.attach(drum, face="S", offset=-1),
    "an unknown relation": lambda lt, drum, line: lt.attach(drum, face="S", relation="x"),
    "a bad face": lambda lt, drum, line: lt.attach(drum, face="Q", offset=10),
    "an old face and a bad angle": lambda lt, drum, line: lt.attach(drum, at="S", angle="bad"),
}


@pytest.mark.parametrize("case", sorted(_BAD_ATTACH))
def test_a_refused_attach_changes_no_field_and_warns_nothing(case: str):
    fs, drum, _, line = _hosts()
    lt = fs.add_instrument("LT", 100, near=drum, face="W", offset=60, angle=30)
    fields = ("host", "at", "face", "offset", "angle", "relation")
    before = [getattr(lt, name) for name in fields]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises((TypeError, ValueError)):
            _BAD_ATTACH[case](lt, drum, line)
    assert caught == []
    assert [getattr(lt, name) for name in fields] == before


@pytest.mark.parametrize("typed, side", [("S", "S"), ("bottom", "S"), ("w", "W")])
def test_the_warning_names_the_face_that_was_typed(typed: str, side: str):
    """Check that the ``at=`` deprecation names the face typed and places the balloon there."""
    fs, drum, _, _ = _hosts()
    with pytest.warns(DeprecationWarning) as caught:
        lt = fs.add_instrument("LT", 101, sensing=drum, at=typed)
    message = str(caught[0].message)
    assert f"at={typed!r} (a unit face)" in message
    assert message.endswith(f"use face={side!r}, or face: {side} in a spec")
    assert [i.message for i in fs.validate() if i.code == "deprecated"] == [message]
    assert lt.face == side


_OLD_FACE = {
    "add_instrument": lambda fs, lt, drum, fe: fs.add_instrument("LT", 1, sensing=drum, at="S"),
    "add_balloon": lambda fs, lt, drum, fe: fs.add_balloon(fe, at="S"),
    "attach": lambda fs, lt, drum, fe: lt.attach(drum, at="S"),
}


@pytest.mark.parametrize("case", sorted(_OLD_FACE))
def test_a_deprecation_raised_as_an_error_changes_nothing(case: str):
    """Check that an ``at=`` deprecation raised as an error leaves the sheet unchanged."""
    fs, drum, fe, _ = _hosts()
    lt = fs.add_instrument("LT", 100, sensing=drum, face="W")
    fields = ("host", "at", "face", "offset", "angle", "relation")
    before = (fs.to_dict(), [getattr(lt, name) for name in fields], fe.tag, fe.balloon)
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        with pytest.raises(DeprecationWarning):
            _OLD_FACE[case](fs, lt, drum, fe)
    assert (fs.to_dict(), [getattr(lt, name) for name in fields], fe.tag, fe.balloon) == before
    assert [i for i in fs.validate() if i.code == "deprecated"] == []


# --- layout ------------------------------------------------------------------


def test_attached_balloons_take_no_rank():
    fs = Flowsheet("rank")
    feed = fs.add(U.Feed("Feed"))
    prod = fs.add(U.Product("Product"))
    s = fs.connect(feed.outlet, prod.inlet)
    ft = fs.add_instrument("FT", 101, sensing=s, offset=60)
    fic = fs.add_instrument("FIC", 101, near=ft, face="N", offset=60)
    fs.connect(ft.sig_out, fic.sig_in, kind="electric")
    fs.layout()
    assert (ft.frame.col, ft.frame.row) == (None, None)
    assert prod.frame.col == 1  # the balloons did not push Product down the ranks
    assert prod.frame.row == 0  # nor open a second row for them


def test_attachment_survives_a_second_layout():
    fs, _, ft, _ = _line(at=0.4, offset=50)
    before = (ft.frame.x, ft.frame.y)
    fs.layout()
    fs.route()
    assert (ft.frame.x, ft.frame.y) == pytest.approx(before)


# --- standing a colliding balloon off ----------------------------------------


def _centre(u: U.Unit) -> tuple[float, float]:
    f = frame_of(u)
    return (f.cx, f.cy)


def _tap_of(inst: U.Instrument) -> tuple[float, float]:
    assert inst.tap is not None, f"{inst.name} has no tap"
    return inst.tap


def _overlaps(a: U.Unit, b: U.Unit) -> bool:
    """Return whether two units' drawn boxes overlap by more than ``validate``'s tolerance."""
    from pandid.portgeom import unit_box

    p, q = unit_box(a, frame_of(a)), unit_box(b, frame_of(b))
    return not (
        p[2] - 1.0 <= q[0] or q[2] - 1.0 <= p[0] or p[3] - 1.0 <= q[1] or q[3] - 1.0 <= p[1]
    )


def test_the_search_and_the_checker_call_the_same_pair_collided():
    """Check that the placer's ``TOUCHING`` equals ``validate``'s tolerance."""
    from pandid.layout.attach import TOUCHING
    from pandid.validate import _TOL

    assert TOUCHING == _TOL


def test_two_bubbles_on_one_tap_do_not_land_on_each_other():
    """Check that three balloons on one tap do not overlap and keep the same tap."""
    fs, s, first, _ = _line(at=0.5, offset=60)
    second = fs.add_instrument("PT", 102, sensing=s, at=0.5, offset=60)
    third = fs.add_instrument("TT", 103, sensing=s, at=0.5, offset=60)
    fs.route()
    assert not _overlaps(first, second)
    assert not _overlaps(first, third)
    assert not _overlaps(second, third)
    # The anchor is not what moved: all three still read the same point.
    assert _tap_of(second) == pytest.approx(_tap_of(first))
    assert _tap_of(third) == pytest.approx(_tap_of(first))


def test_a_bubble_is_stood_off_the_equipment_it_would_have_landed_on():
    """Check that a balloon aimed into a valve is stood off it, its tap unmoved."""
    # angle=0 aims the standoff along the flow, straight into FV-101:
    # the tap is 19px short of the valve and the bubble is 44 across.
    fs, _, inst, fv = _line(at=0.9, offset=45, angle=0)
    assert not _overlaps(inst, fv)
    # The anchor did not move: still on the run, still short of the valve.
    tap = _tap_of(inst)
    assert tap[1] == pytest.approx(195.0)
    assert tap[0] < frame_of(fv).x
    assert math.dist(_centre(inst), tap) >= 45 - 1e-6


def test_a_bubble_mounted_flush_is_pushed_clear_of_the_wall():
    """Check that a balloon mounted flush on a vessel face is pushed clear of the vessel."""
    fs = Flowsheet("flush")
    drum = fs.add(U.Vessel("V-1")).pin(x=300, y=250)
    lt = fs.add_instrument("LT", 1, sensing=drum, face="E", offset=10)
    fs.route()
    assert not _overlaps(lt, drum)
    face = frame_of(drum)
    assert _tap_of(lt) == pytest.approx((face.x_max, face.cy))


def test_the_standoff_only_ever_grows():
    """Check that a crowd of balloons on one tap keep at least their offset and never overlap."""
    fs, s, first, _ = _line(at=0.5, offset=45)
    crowd = [fs.add_instrument("PT", 200 + i, sensing=s, at=0.5, offset=45) for i in range(5)]
    fs.route()
    every = [first, *crowd]
    for inst in every:
        assert math.dist(_centre(inst), _tap_of(inst)) >= 45 - 1e-6
    for i, a in enumerate(every):
        for b in every[i + 1 :]:
            assert not _overlaps(a, b), f"{a.name} and {b.name}"


def test_a_nozzle_keepout_is_the_stand_off_in_front_of_a_live_nozzle():
    """Check that each connected nozzle has one keepout reaching out along its face."""
    from pandid.layout.attach import _nozzle_keepouts
    from pandid.portgeom import port_anchor
    from pandid.routing.visibility import MIN_ESCAPE

    fs, _, _, fv = _line(at=0.5, offset=45)
    keepouts = _nozzle_keepouts(fs)
    live = [(u, n) for u in fs.units for n, p in u.ports.items() if p.stream is not None]
    assert len(keepouts) == len(live)
    ax, ay, facing = port_anchor(fv, frame_of(fv), "inlet")
    assert facing == "W"
    assert (ax - MIN_ESCAPE, ay, ax, ay) in keepouts


def test_a_moved_bubble_leaves_a_nozzle_its_room_to_escape():
    """Check that a moved balloon is stood further off rather than across a nozzle keepout."""
    from pandid.layout.attach import _anchor, _clear_standoff, _standoff_box

    fs, _, inst, _ = _line(at=0.5, offset=45)
    anchor = _anchor(inst)
    assert anchor is not None
    tap, ref = anchor
    w, h = 44.0, 44.0
    # Stand something exactly where it asked to be, so it has to move,
    # and read off where it goes with nothing else in the way.
    blocked = [_standoff_box(tap, ref, inst.offset, inst.angle, w, h)]
    swung = _clear_standoff(inst, tap, ref, w, h, blocked, [])
    assert swung != (inst.offset, inst.angle)

    # Now put a nozzle stand-off across exactly that answer. The search
    # has to give it up for a further one; the anchor is untouched either
    # way, and the standoff only ever grows.
    keepout = _standoff_box(tap, ref, *swung, w, h)
    guarded = _clear_standoff(inst, tap, ref, w, h, blocked, [keepout])
    assert guarded != swung
    assert guarded[0] >= inst.offset


def test_an_in_line_element_is_never_stood_off():
    """Check that an element at ``offset=0`` stays on its tap even where it overlaps a valve."""
    fs, _, fe, fv = _line(at=0.95, offset=0)
    assert _overlaps(fe, fv)  # the search had something to react to
    assert _centre(fe) == pytest.approx(_tap_of(fe))


def test_a_crowded_sheet_places_the_same_way_every_time():
    """Check that a crowded tap places its balloons the same way every time."""

    def boxes() -> list[tuple[str, float, float]]:
        fs, s, _, _ = _line(at=0.5, offset=50)
        for i in range(6):
            fs.add_instrument("PT", 300 + i, sensing=s, at=0.5, offset=50)
        fs.route()
        return [(u.name, *_centre(u)) for u in fs.units if u.frame is not None]

    first = boxes()
    assert boxes() == first
    assert boxes() == first


# --- a balloon the author placed ---------------------------------------------


def test_a_pinned_balloon_lands_where_it_was_pinned():
    """Check that a pinned attached balloon lands on its pin, keeps its tap and is not reported."""
    fs, _, inst, _ = _line()
    assert inst.frame is not None
    tap = _tap_of(inst)
    assert (inst.frame.x, inst.frame.y) != (1120.0, 760.0)

    inst.pin(x=1120.0, y=760.0)
    fs.route()

    assert inst.frame is not None
    assert (inst.frame.x, inst.frame.y) == (1120.0, 760.0)
    assert _tap_of(inst) == tap
    assert "pin-not-honored" not in [i.code for i in fs.validate()]


def test_a_pinned_balloon_is_never_walked_off_what_it_was_put_on():
    """Check that a balloon pinned onto a valve stays there and the overlap is reported."""
    fs, _, inst, fv = _line()
    assert fv.frame is not None
    inst.pin(x=fv.frame.x, y=fv.frame.y)
    fs.route()

    assert inst.frame is not None
    assert (inst.frame.x, inst.frame.y) == (fv.frame.x, fv.frame.y)
    codes = [i.code for i in fs.validate()]
    assert "unit-overlap" in codes and "pin-not-honored" not in codes


def test_one_pinned_axis_leaves_the_other_to_the_standoff():
    """Check that a balloon pinned on one axis keeps the resolver's place on the other."""
    fs, _, inst, _ = _line()
    assert inst.frame is not None
    free_x, free_y = inst.frame.x, inst.frame.y

    inst.pin(x=free_x + 240.0)
    fs.route()

    assert inst.frame is not None
    assert inst.frame.x == free_x + 240.0
    assert inst.frame.y == free_y, "the axis nobody stated is still the resolver's"


def test_a_balloon_pinned_by_a_nozzle_lands_that_nozzle():
    """Check that ``pin(port=...)`` puts a balloon's signal terminal on the given point."""
    fs, _, inst, _ = _line()

    inst.pin(port="pv", x=700.0, y=500.0)
    fs.route()

    assert inst.frame is not None
    assert port_point(inst, inst.frame, "pv") == (700.0, 500.0)
    assert "pin-not-honored" not in [i.code for i in fs.validate()]


# --- final control element ---------------------------------------------------


def test_controller_output_routes_to_the_valve_actuator():
    from pandid.layout.attach import stream_path
    from pandid.portgeom import port_point

    fs, _, ft, fv = _line(at=0.4, offset=60)
    fic = fs.add_instrument("FIC", 101, near=ft, face="N", offset=120, angle=35, display="central")
    fs.connect(ft.sig_out, fic.sig_in, kind="electric")
    sig = fs.connect(fic.sig_out, fv.actuator, kind="pneumatic")
    fs.route()
    end = port_point(fv, fv.frame, "actuator")
    drawn = stream_path(sig)
    assert drawn[0] == pytest.approx(port_point(fic, fic.frame, "sig_out"))
    assert drawn[-1] == pytest.approx(end)
    assert drawn[-2][0] == pytest.approx(end[0])  # arrives square onto the top
    # the actuator is on top of the valve, not on either process nozzle
    assert end[1] < fv.frame.cy
    assert fv.frame.x < end[0] < fv.frame.x_max
    assert _hatch_marks(fs.to_svg()) >= 2  # pneumatic slash ticks drawn


def _level_loop() -> tuple[Flowsheet, U.Instrument, U.Valve]:
    """Return a drum's level loop: LT-101 wired to a free LIC-101, and LV-101 on the outlet."""
    fs = Flowsheet("level")
    feed = fs.add(U.Feed("Feed"))
    drum = fs.add(U.Vessel("V-1"))
    lv = fs.add(U.Valve("LV-101", variant="control"))
    prod = fs.add(U.Product("Product"))
    fs.connect(feed.outlet, drum.inlet)
    fs.connect(drum.outlet, lv.inlet)
    fs.connect(lv.outlet, prod.inlet)
    lt = fs.add_instrument("LT", 101, sensing=drum)
    lic = fs.add_instrument("LIC", 101)
    fs.connect(lt.sig_out, lic.sig_in, kind="electric")
    return fs, lic, lv


def test_an_unanchored_controller_hangs_beyond_the_actuator_it_drives():
    """Check that a free controller hangs 100 out past the actuator, on its axis."""
    from pandid.portgeom import port_anchor

    fs, lic, lv = _level_loop()
    fs.connect(lic.sig_out, lv.actuator, kind="electric")
    fs.route()

    valve = frame_of(lv)
    ax, ay, face = port_anchor(lv, valve, "actuator")
    cx, cy = _centre(lic)
    beyond = {"N": valve.y - cy, "S": cy - valve.y_max, "W": valve.x - cx, "E": cx - valve.x_max}
    assert beyond[face] > 0, f"LIC-101 is not on the {face} side of LV-101"
    assert (cx if face in "NS" else cy) == pytest.approx(ax if face in "NS" else ay, abs=0.5)
    assert math.dist((cx, cy), (ax, ay)) == pytest.approx(100.0, abs=1.0)
    assert [i.code for i in fs.validate() if i.severity == "error"] == []


def test_hanging_a_controller_off_its_valve_writes_nothing_into_the_model():
    """Check that hanging a controller writes nothing to the spec and repeats on relayout."""
    from pandid.portgeom import port_anchor

    fs, lic, lv = _level_loop()
    fs.connect(lic.sig_out, lv.actuator, kind="electric")
    spec = fs.to_dict()
    fs.layout()
    fs.route()

    ax, ay, _ = port_anchor(lv, frame_of(lv), "actuator")
    first = _centre(lic)
    assert math.dist(first, (ax, ay)) == pytest.approx(100.0, abs=1.0)
    assert lic.host is None
    assert fs.to_dict() == spec
    fs.layout()
    fs.route()
    assert _centre(lic) == pytest.approx(first)
    assert fs.to_dict() == spec


def test_a_controller_driving_no_actuator_is_not_hung():
    """Check that a controller driving a relay rather than the actuator gets no spot."""
    from pandid.layout.control import _actuator_spot

    fs, lic, lv = _level_loop()
    ly = fs.add_instrument("LY", 101, near=lv, face="N")
    fs.connect(lic.sig_out, ly.sig_in, kind="electric")
    fs.connect(ly.sig_out, lv.actuator, kind="pneumatic")
    fs.route()

    assert _actuator_spot(fs, lic, 44.0, 44.0, []) is None


def test_a_controller_too_big_for_the_actuator_spot_is_placed_free():
    """Check that a controller too big for the actuator spot is placed clear of the valve."""
    fs = Flowsheet("big")
    valve = fs.add(U.Valve("V", variant="control")).pin(x=300, y=300)
    lic = fs.add(U.Instrument("LIC", 1, width=600, height=600))
    fs.connect(lic.sig_out, valve.actuator, kind="electric")
    fs.route()

    assert not _overlaps(lic, valve)
    assert [i.code for i in fs.validate() if i.severity == "error"] == []


def test_a_controller_is_not_hung_across_a_pipe():
    """Check that a controller is not hung across a pipe through the actuator's standoff."""
    fs = Flowsheet("pipe")
    feed = fs.add(U.Feed("Feed")).pin(port="outlet", x=100, y=100)
    fv = fs.add(U.Valve("FV-1", variant="control")).pin(port="inlet", x=300, y=212.4)
    prod = fs.add(U.Product("Product")).pin(port="inlet", x=600, y=212.4)
    fs.connect(feed.outlet, fv.inlet).via([(400, 100), (400, 160), (275, 160), (275, 212.4)])
    fs.connect(fv.outlet, prod.inlet)
    fic = fs.add(U.Instrument("FIC", 1))
    fs.connect(fic.sig_out, fv.actuator, kind="electric")
    fs.route()

    assert "route-crosses-unit" not in {i.code for i in fs.validate()}


def test_a_controller_driving_two_actuators_reads_back_in_place():
    """Check that a controller driving two actuators reads back from the spec in place."""
    fs = Flowsheet("split")
    first = fs.add(U.Valve("FV-1", variant="control")).pin(x=100, y=300)
    second = fs.add(U.Valve("FV-2", variant="control")).pin(x=500, y=300)
    fic = fs.add(U.Instrument("FIC", 1))
    third_out = fic.signal_port("sig_out_3")
    fs.connect(fic.signal_port("sig_out_2"), second.actuator, kind="electric")
    fs.connect(third_out, first.actuator, kind="electric")
    fs.route()
    rebuilt = Flowsheet.from_dict(fs.to_dict())
    rebuilt.route()

    (twin,) = [u for u in rebuilt.units if u.name == "FIC-1"]
    assert _centre(twin) == pytest.approx(_centre(fic))


def test_a_controller_hangs_from_the_actuators_own_point():
    """Check that a controller hangs square to an off-centre actuator."""
    from pandid.portgeom import port_anchor

    fs = Flowsheet("angle")
    valve = fs.add(U.Valve("V", variant="angle", width=198, height=198)).pin(x=300, y=300)
    lic = fs.add(U.Instrument("LIC", 1))
    fs.connect(lic.sig_out, valve.actuator, kind="electric")
    fs.route()

    ax, ay, face = port_anchor(valve, frame_of(valve), "actuator")
    assert face == "N"
    assert abs(ax - frame_of(valve).cx) > 1.0, "the actuator has to be off the face's middle"
    assert _centre(lic) == pytest.approx((ax, ay - 100.0))


def _hung_controller() -> tuple[Flowsheet, U.Instrument, U.Valve]:
    """Return a free LIC-1 driving the actuator of a pinned valve."""
    fs = Flowsheet("review")
    valve = fs.add(U.Valve("V", variant="control")).pin(x=300, y=300)
    lic = fs.add_instrument("LIC", 1)
    fs.connect(lic.sig_out, valve.actuator, kind="electric")
    return fs, lic, valve


def test_a_hung_controller_clears_a_balloon_pinned_after_it():
    """Check that a hung controller stands clear of a balloon pinned on its spot."""
    fs, lic, _ = _hung_controller()
    pi = fs.add_instrument("PI", 1).pin(x=300, y=178)
    fs.route()

    assert not _overlaps(lic, pi)


def test_a_hung_controller_clears_a_signal_line():
    """Check that a hung controller stands clear of a signal line through its spot."""
    fs, _, _ = _hung_controller()
    first = fs.add_instrument("XI", 1).pin(x=100, y=178)
    second = fs.add_instrument("XI", 2).pin(x=600, y=178)
    fs.connect(first.sig_out, second.sig_in, kind="electric").via([(200, 200), (500, 200)])
    fs.route()

    assert "route-crosses-unit" not in {i.code for i in fs.validate()}


def test_a_hung_controller_clears_a_tap_line():
    """Check that a hung controller stays off a tap line rising past the actuator."""
    from pandid.layout.conflicts import segment_crosses_box
    from pandid.portgeom import unit_box
    from pandid.render.svg import tap_lines, tap_route

    fs, lic, valve = _hung_controller()
    fs.route()
    fs.add_instrument("PI", 1, sensing=valve, face="N", offset=100)
    fs.layout()
    fs.route()

    box = unit_box(lic, frame_of(lic))
    lines = [tap_route(u, tap, centre) for u, tap, centre in tap_lines(fs)]
    assert lines, "PI-1 draws a tap line"
    for route in lines:
        assert not any(segment_crosses_box(a, b, box) for a, b in zip(route, route[1:]))


def test_a_hung_controller_keeps_its_own_tap_line() -> None:
    """Check that a balloon tapped on a hung controller keeps its tap on the north face."""
    from pandid.portgeom import face_point

    fs, lic, _ = _hung_controller()
    pi = fs.add_instrument("PI", 1, sensing=lic, face="N", offset=100)
    fs.route()

    assert fs.route_converged
    assert pi.tap == pytest.approx(face_point(lic, frame_of(lic), "N")[0])


def test_a_hung_controller_clears_a_balloon_pinned_on_the_grid() -> None:
    """Check that a hung controller stands clear of a balloon pinned by grid rank."""
    fs = Flowsheet("grid")
    valve = fs.add(U.Valve("V", variant="control")).pin(col=0, row=0)
    lic = fs.add_instrument("LIC", 1)
    fs.connect(lic.sig_out, valve.actuator, kind="electric")
    fs.add_instrument("PI", 1).pin(col=0, row=-1)
    fs.route()

    assert [i.code for i in fs.validate() if i.code == "unit-overlap"] == []


def test_a_controller_carrying_a_balloon_is_not_hung() -> None:
    """Check that a controller carrying a balloon is not hung across the valve."""
    from pandid.layout.conflicts import segment_crosses_box
    from pandid.portgeom import unit_box
    from pandid.render.svg import tap_lines, tap_route

    fs, lic, valve = _hung_controller()
    fs.add_instrument("PI", 1, sensing=lic, face="S", offset=140)
    fs.route()

    box = unit_box(valve, frame_of(valve))
    ((inst, tap, centre),) = tap_lines(fs)
    route = tap_route(inst, tap, centre)
    assert not any(segment_crosses_box(a, b, box) for a, b in zip(route, route[1:]))


def test_a_controller_with_a_hand_routed_line_is_not_hung() -> None:
    """Check that a controller whose line is routed by hand is not hung on that line."""
    fs, lic, valve = _hung_controller()
    line = lic.sig_out.stream
    assert line is not None
    line.via([(280, 200), (500, 200)])
    fs.route()

    assert [i.code for i in fs.validate() if i.code == "route-crosses-unit"] == []


def test_a_controller_is_not_hung_where_its_line_passes_through_it_twice() -> None:
    """Check that hanging is refused where it adds a leg through the controller."""
    from pandid.layout.attach import stream_path
    from pandid.layout.conflicts import segment_crosses_box
    from pandid.portgeom import unit_box

    fs, lic, _ = _hung_controller()
    line = lic.sig_out.stream
    assert line is not None
    line.via([(100, 200), (500, 200)])
    fs.route()

    box, path = unit_box(lic, frame_of(lic)), stream_path(line)
    assert sum(segment_crosses_box(a, b, box) for a, b in zip(path, path[1:])) == 1


def test_a_hung_controllers_line_clears_a_balloon_on_the_actuator() -> None:
    """Check that a hung controller's line misses a balloon hung on the actuator face."""
    fs, _, valve = _hung_controller()
    fs.add_instrument("PI", 1, sensing=valve, face="N", offset=46)
    fs.route()

    assert [i.code for i in fs.validate() if i.code == "route-crosses-unit"] == []


def test_a_controller_with_a_balloon_on_its_line_is_not_hung() -> None:
    """Check that a controller with a balloon on its line is not hung over it."""
    fs = Flowsheet("inline")
    valve = fs.add(U.Valve("V", variant="control")).pin(x=300, y=300, orientation=270)
    lic = fs.add_instrument("LIC", 1)
    signal = fs.connect(lic.sig_out, valve.actuator, kind="electric")
    fs.add_instrument("ZI", 1, sensing=signal, at=0.9, offset=0)
    fs.route()

    assert [i.code for i in fs.validate() if i.code == "unit-overlap"] == []


def test_a_controller_wired_from_behind_its_valve_is_not_hung() -> None:
    """Check that a controller wired from behind its valve is not hung across it."""
    fs = Flowsheet("behind")
    valve = fs.add(U.Valve("V", variant="control")).pin(x=100, y=350, orientation=180)
    lic = fs.add_instrument("LIC", 1)
    fs.connect(lic.sig_out, valve.actuator, kind="electric")
    lt = fs.add_instrument("LT", 1).pin(x=100, y=300)
    fs.connect(lt.sig_out, lic.sig_in, kind="electric")
    fs.route()

    assert [i.code for i in fs.validate() if i.code == "route-crosses-unit"] == []


def _close_transmitter() -> Flowsheet:
    """Return a free LIC-1 on a turned valve, with LT-1 pinned close by."""
    fs = Flowsheet("close")
    valve = fs.add(U.Valve("V", variant="control")).pin(x=300, y=300, orientation=90)
    lic = fs.add_instrument("LIC", 1)
    fs.connect(lic.sig_out, valve.actuator, kind="electric")
    lt = fs.add_instrument("LT", 1).pin(x=450, y=275)
    lt.nozzle("sig_out", face="N")
    fs.connect(lt.sig_out, lic.sig_in, kind="electric")
    return fs


def _two_transmitters() -> Flowsheet:
    """Return a free LIC-1 that drives no actuator and reads two pinned transmitters."""
    fs = Flowsheet("no-actuator")
    fs.add(U.Valve("V", variant="control")).pin(x=300, y=300)
    lic = fs.add_instrument("LIC", 1)
    lt1 = fs.add_instrument("LT", 1).pin(x=325, y=275)
    lt2 = fs.add_instrument("LT", 2).pin(x=325, y=325)
    fs.connect(lt1.sig_out, lic.sig_in, kind="electric")
    fs.connect(lt2.sig_out, lic.signal_port("sig_in_2"), kind="electric")
    return fs


def _cascade() -> Flowsheet:
    """Return LIC-1 and FIC-1 driving valves 50 apart and wired to each other."""
    fs = Flowsheet("cascade")
    va = fs.add(U.Valve("VA", variant="control")).pin(x=300, y=300)
    vb = fs.add(U.Valve("VB", variant="control")).pin(x=300, y=350)
    lic = fs.add_instrument("LIC", 1)
    fic = fs.add_instrument("FIC", 1)
    fs.connect(lic.sig_out, va.actuator, kind="electric")
    fs.connect(fic.sig_out, vb.actuator, kind="electric")
    fs.connect(lic, fic, kind="electric")
    return fs


def _crossed_cascade() -> Flowsheet:
    """Return two turned valves whose controllers are in cascade, with LT-1 and PI-1 nearby."""
    fs = Flowsheet("fallback")
    va = fs.add(U.Valve("VA", variant="control")).pin(x=300, y=500, orientation=270)
    vb = fs.add(U.Valve("VB", variant="control")).pin(x=350, y=550, orientation=90)
    lic = fs.add_instrument("LIC", 1)
    fic = fs.add_instrument("FIC", 1)
    fs.connect(lic.sig_out, va.actuator, kind="electric")
    fs.connect(fic.sig_out, vb.actuator, kind="electric")
    lt = fs.add_instrument("LT", 1).pin(x=450, y=500)
    fs.connect(lt.sig_out, lic.sig_in, kind="electric")
    fs.connect(lic.signal_port("sig_out_2"), fic.sig_in, kind="electric")
    fs.add_instrument("PI", 1, sensing=vb, face="S", offset=60)
    return fs


def _tap_past_a_transmitter() -> Flowsheet:
    """Return PI-1 hung off a turned valve near the LT-1 that LIC-1 reads."""
    fs = Flowsheet("tap")
    valve = fs.add(U.Valve("V", variant="control")).pin(x=300, y=300, orientation=180)
    lic = fs.add_instrument("LIC", 1)
    fs.connect(lic.sig_out, valve.actuator, kind="electric")
    lt = fs.add_instrument("LT", 1).pin(x=250, y=350)
    fs.connect(lt.sig_out, lic.sig_in, kind="electric")
    fs.add_instrument("PI", 1, sensing=valve, face="S", offset=100, angle=45)
    return fs


def _drawn_by_hand() -> Flowsheet:
    """Return a free LIC-1 whose line to the actuator is drawn by hand."""
    fs = Flowsheet("manual")
    valve = fs.add(U.Valve("V", variant="control")).pin(x=300, y=300)
    lic = fs.add_instrument("LIC", 1)
    lic.nozzle("sig_out", face="E")
    fs.connect(lic.sig_out, valve.actuator, kind="electric").via(
        [(284.25, 234.9), (312.2, 234.9), (312.2, 275)]
    )
    return fs


def _balloon_on_a_signal_line() -> Flowsheet:
    """Return PI-1 on a signal line between two indicators near LIC-1's valve."""
    fs = Flowsheet("signal balloon")
    valve = fs.add(U.Valve("V", variant="control")).pin(x=300, y=300)
    lic = fs.add_instrument("LIC", 1)
    fs.connect(lic.sig_out, valve.actuator, kind="electric")
    lt = fs.add_instrument("LT", 1).pin(x=300, y=350)
    fs.connect(lt.sig_out, lic.sig_in, kind="electric")
    x1 = fs.add_instrument("XI", 1).pin(x=200, y=300)
    x2 = fs.add_instrument("XI", 2).pin(x=550, y=500)
    line = fs.connect(x1.sig_out, x2.sig_in, kind="electric")
    fs.add_instrument("PI", 1, sensing=line, at=0.5, offset=60)
    return fs


@pytest.mark.parametrize(
    "build",
    [
        _balloon_on_a_signal_line,
        _close_transmitter,
        _two_transmitters,
        _cascade,
        _crossed_cascade,
        _tap_past_a_transmitter,
        _drawn_by_hand,
    ],
)
def test_a_hung_controller_that_leaves_a_clash_is_placed_from_its_wiring(
    build: Callable[[], Flowsheet],
) -> None:
    """Check that a clash from hanging gives way to placing the controller from its wiring."""
    from pandid.layout.conflicts import segment_crosses_box
    from pandid.portgeom import unit_box
    from pandid.render.svg import tap_lines, tap_route

    fs = build()
    fs.route()

    codes = ("route-crosses-unit", "route-diagonal")
    assert [i.code for i in fs.validate() if i.severity == "error" or i.code in codes] == []
    for inst, tap, centre in tap_lines(fs):
        route = tap_route(inst, tap, centre)
        for u in fs.units:
            if u is inst or u is inst.host or u.frame is None:
                continue
            box = unit_box(u, u.frame)
            assert not any(segment_crosses_box(a, b, box) for a, b in zip(route, route[1:]))


def test_a_router_that_freezes_its_routes_still_gets_the_fallback() -> None:
    """Check that a router freezing every route still gets a sheet with no slanted line."""
    from pandid.routing import DefaultRouter

    class FreezeRouter(DefaultRouter):
        def route(self, fs: Flowsheet) -> None:
            super().route(fs)
            for stream in fs.streams:
                assert stream.route is not None
                stream.route.manual = True

    fs, _, _ = _hung_controller()
    fs.route(FreezeRouter())

    assert [i.code for i in fs.validate() if i.code == "route-diagonal"] == []


def test_a_custom_router_routes_the_sheet_without_hanging() -> None:
    """Check that a router freezing only its straight routes leaves no slanted line."""
    from pandid.routing import DefaultRouter

    class FreezeStraightRouter(DefaultRouter):
        def route(self, fs: Flowsheet) -> None:
            super().route(fs)
            for stream in fs.streams:
                assert stream.route is not None
                if len({x for x, _ in stream.route.waypoints}) == 1:
                    stream.route.manual = True

    fs, _, _ = _hung_controller()
    fs.route(FreezeStraightRouter())

    assert [i.code for i in fs.validate() if i.code == "route-diagonal"] == []


def test_the_fallback_lays_out_with_an_engine_that_wraps_the_default() -> None:
    """Check that the fallback reruns an engine that wraps ``fs.layout()`` and moves a unit."""

    class WrappedEngine:
        def layout(self, fs: Flowsheet) -> None:
            fs.layout()
            assert marker.frame is not None
            marker.frame.x = marker.frame.y = 1200

    fs = _close_transmitter()
    marker = fs.add(U.Vessel("marker"))
    fs.layout(WrappedEngine())
    fs.route()

    assert marker.frame is not None
    assert (marker.frame.x, marker.frame.y) == (1200, 1200)


def test_a_router_that_refuses_the_hung_sheet_gets_the_fallback() -> None:
    """Check that a router raising on the hung sheet routes the unhung sheet instead."""
    from pandid.routing import DefaultRouter

    class CheckingRouter(DefaultRouter):
        def route(self, fs: Flowsheet) -> None:
            super().route(fs)
            for issue in fs.validate():
                if issue.code == "route-crosses-unit":
                    raise ValueError(issue.message)

    fs = _close_transmitter()
    fs.route(CheckingRouter())

    assert [i.code for i in fs.validate() if i.code == "route-crosses-unit"] == []


def test_the_fallback_keeps_an_engine_that_refines_the_layout() -> None:
    """Check that a refining engine is not rerun and the sheet routes without errors."""

    class SnapToGrid:
        def layout(self, fs: Flowsheet) -> None:
            for u in fs.units:
                assert u.frame is not None
                u.frame.x = round(u.frame.x)

    fs = _close_transmitter()
    fs.layout()
    fs.layout(SnapToGrid())
    fs.route()

    assert [i for i in fs.validate() if i.severity == "error"] == []


def test_a_hung_controller_keeps_out_of_a_tag_halo() -> None:
    """Check that a hung controller stays out of a nearby tag's halo."""
    from pandid.layout.control import _halos
    from pandid.portgeom import unit_box

    fs, lic, _ = _hung_controller()
    fs.add(U.Pump("P-101", width=44, height=44, label_pos="left")).pin(x=350, y=178)
    fs.route()

    box = unit_box(lic, frame_of(lic))
    for left, top, right, bottom in _halos(fs):
        assert not (box[0] < right and left < box[2] and box[1] < bottom and top < box[3])


def test_the_fallback_starts_from_the_settled_state_it_saved() -> None:
    """Check that a router reading ``route_converged`` sees the pre-hanging value."""
    from pandid.routing import DefaultRouter

    class CheckingRouter(DefaultRouter):
        def route(self, fs: Flowsheet) -> None:
            super().route(fs)
            if any(i.code == "route-not-settled" for i in fs.validate()):
                raise ValueError("unsettled")

    fs, _, _ = _hung_controller()
    fs.route(CheckingRouter())

    assert fs.route_converged


def test_a_line_drawn_by_hand_after_routing_is_routed_from_the_unhung_sheet() -> None:
    """Check that a line drawn by hand after routing stays square on the next route."""
    fs, lic, valve = _hung_controller()
    line = lic.sig_out.stream
    assert line is not None
    fs.route()
    line.via([(284.25, 234.9), (312.2, 234.9), (312.2, 275)])
    fs.route()

    assert [i.code for i in fs.validate() if i.code == "route-diagonal"] == []


def test_a_hung_controllers_line_keeps_out_of_a_tag_halo() -> None:
    """Check that a controller's line routes round a tag lying across it."""
    from pandid.layout.attach import stream_path
    from pandid.layout.conflicts import segment_crosses_box
    from pandid.layout.control import _halos

    fs, lic, _ = _hung_controller()
    fs.add(U.Vessel("P-101", width=80, height=20, label_pos="left")).pin(x=330, y=235)
    fs.route()

    line = lic.sig_out.stream
    assert line is not None
    points = stream_path(line)
    for halo in _halos(fs):
        assert not any(segment_crosses_box(a, b, halo) for a, b in zip(points, points[1:]))


def test_a_hung_line_frozen_with_via_is_drawn_as_frozen() -> None:
    """Check that a hung line frozen with ``via()`` stays square on the next route."""
    fs, lic, _ = _hung_controller()
    line = lic.sig_out.stream
    assert line is not None
    fs.route()
    assert line.route is not None
    line.via(list(line.route.waypoints))
    fs.route()

    assert [i.code for i in fs.validate() if i.code == "route-diagonal"] == []


def test_a_balloon_moved_by_hanging_keeps_out_of_a_tag_halo() -> None:
    """Check that a hung controller and the balloon it moves stay out of a tag halo."""
    from pandid.layout.control import _halos
    from pandid.portgeom import unit_box

    fs, lic, _ = _hung_controller()
    xi = fs.add_instrument("XI", 1)
    fs.connect(lic.signal_port("sig_out_2"), xi.sig_in, kind="electric")
    fs.add(U.Pump("P-101-ABCDEF", width=44, height=44, label_pos="left")).pin(x=350, y=103)
    fs.route()

    for unit in (lic, xi):
        box = unit_box(unit, frame_of(unit))
        for left, top, right, bottom in _halos(fs):
            assert not (box[0] < right and left < box[2] and box[1] < bottom and top < box[3])


def test_a_route_drawn_by_hand_and_then_cleared_stays_cleared() -> None:
    """Check that a hand-drawn route cleared after a hung route stays cleared."""
    fs, _, _ = _hung_controller()
    feed = fs.add(U.Feed("Feed")).pin(x=100, y=700)
    prod = fs.add(U.Product("Product")).pin(x=600, y=700)
    pipe = fs.connect(feed.outlet, prod.inlet).via([(200, 700), (200, 600), (500, 600), (500, 700)])
    fs.route()
    pipe.route = None
    fs.route()

    assert "via" not in fs.to_dict()["streams"][-1]


def test_a_copied_sheet_routes_from_its_own_unhung_state() -> None:
    """Check that a deep copy of a hung sheet keeps a later hand-drawn line square."""
    import copy

    fs, _, _ = _hung_controller()
    fs.route()
    fs = copy.deepcopy(fs)
    fs.streams[0].via([(284.25, 234.9), (312.2, 234.9), (312.2, 275)])
    fs.route()

    assert [i.code for i in fs.validate() if i.code == "route-diagonal"] == []


def test_a_balloon_added_after_hanging_is_laid_out_from_the_unhung_sheet() -> None:
    """Check that a balloon added after hanging settles with its tap on the line."""
    from pandid.layout.attach import stream_path

    fs, lic, _ = _hung_controller()
    signal = lic.sig_out.stream
    assert signal is not None
    fs.route()
    pi = fs.add_instrument("PI", 1, sensing=signal, at=0.1, offset=30)
    fs.route()

    assert fs.route_converged
    assert pi.tap is not None
    x, y = pi.tap

    def gap(a: tuple[float, float], b: tuple[float, float]) -> float:
        near_x = min(max(x, min(a[0], b[0])), max(a[0], b[0]))
        near_y = min(max(y, min(a[1], b[1])), max(a[1], b[1]))
        return math.hypot(x - near_x, y - near_y)

    points = stream_path(signal)
    assert min(gap(a, b) for a, b in zip(points, points[1:])) < 0.5


def test_hanging_adds_no_tap_line_through_a_tag_halo() -> None:
    """Check that hanging puts no tap line through a tag halo."""
    from pandid.layout.conflicts import segment_crosses_box
    from pandid.layout.control import _halos
    from pandid.render.svg import tap_lines, tap_route

    fs, lic, _ = _hung_controller()
    xi = fs.add_instrument("XI", 1)
    fs.connect(lic.signal_port("sig_out_2"), xi.sig_in, kind="electric")
    fs.add_instrument("PI", 1, sensing=xi, face="N", offset=100)
    fs.add(U.Pump("P-101", width=44, height=44, label_pos="left")).pin(x=275, y=28)
    fs.route()

    for inst, tap, centre in tap_lines(fs):
        route = tap_route(inst, tap, centre)
        for halo in _halos(fs):
            assert not any(segment_crosses_box(a, b, halo) for a, b in zip(route, route[1:]))


def test_hanging_lays_no_line_along_another() -> None:
    """Check that a hung controller's line does not run along a hand-drawn pipe."""
    from pandid.layout.attach import stream_path
    from pandid.layout.control import _shared

    fs = Flowsheet("coincident")
    valve = fs.add(U.Valve("V", variant="control")).pin(x=300, y=300)
    lic = fs.add_instrument("LIC", 1)
    lic.nozzle("sig_out", face="S")
    feed = fs.add(U.Feed("F")).pin(port="outlet", x=100, y=265)
    prod = fs.add(U.Product("P")).pin(port="inlet", x=600, y=265)
    pipe = fs.connect(feed.outlet, prod.inlet).via(
        [(312.2, 265), (312.2, 275), (500, 275), (500, 265)]
    )
    signal = fs.connect(lic.sig_out, valve.actuator, kind="electric")
    fs.route()

    sp, pp = stream_path(signal), stream_path(pipe)
    assert not any(_shared(a, b, c, d) for a, b in zip(sp, sp[1:]) for c, d in zip(pp, pp[1:]))


def test_hanging_lays_no_line_along_a_tap_line() -> None:
    """Check that a hung controller's line does not run along a tap line."""
    from pandid.layout.attach import stream_path
    from pandid.layout.control import _shared
    from pandid.render.svg import tap_lines, tap_route

    fs = Flowsheet("tap overlap")
    valve = fs.add(U.Valve("V", variant="control")).pin(x=300, y=300)
    lic = fs.add_instrument("LIC", 1)
    lic.nozzle("sig_out", face="S")
    feed = fs.add(U.Feed("F")).pin(port="outlet", x=100, y=270)
    prod = fs.add(U.Product("P")).pin(port="inlet", x=600, y=270)
    pipe = fs.connect(feed.outlet, prod.inlet)
    fs.add_instrument("PI", 1, sensing=pipe, at=0.4244, offset=140, angle=10)
    signal = fs.connect(lic.sig_out, valve.actuator, kind="electric")
    fs.route()

    sp = stream_path(signal)
    for inst, tap, centre in tap_lines(fs):
        tp = tap_route(inst, tap, centre)
        assert not any(_shared(a, b, c, d) for a, b in zip(sp, sp[1:]) for c, d in zip(tp, tp[1:]))


def test_hanging_lays_no_line_along_a_pipe_with_rounding_in_its_track() -> None:
    """Check that a pipe track with rounding still counts as shared with the line."""
    from pandid.layout.attach import stream_path

    def shared(
        a: tuple[float, float],
        b: tuple[float, float],
        c: tuple[float, float],
        d: tuple[float, float],
    ) -> bool:
        if max(abs(a[0] - b[0]), abs(c[0] - d[0]), abs(a[0] - c[0])) >= 1:
            return False
        low = max(min(a[1], b[1]), min(c[1], d[1]))
        return min(max(a[1], b[1]), max(c[1], d[1])) - low > 1

    fs = Flowsheet("overlap")
    valve = fs.add(U.Valve("V", variant="control")).pin(x=300, y=300)
    lic = fs.add_instrument("LIC", 1)
    lic.nozzle("sig_out", face="S")
    feed = fs.add(U.Feed("F")).pin(x=100, y=265)
    prod = fs.add(U.Product("P")).pin(x=600, y=265)
    pipe = fs.connect(feed.outlet, prod.inlet).via(
        [(312.2, 265), (312.1 + 0.1, 275), (500, 275), (500, 265)]
    )
    signal = fs.connect(lic.sig_out, valve.actuator, kind="electric")
    fs.route()

    sp, pp = stream_path(signal), stream_path(pipe)
    assert not any(shared(a, b, c, d) for a, b in zip(sp, sp[1:]) for c, d in zip(pp, pp[1:]))


def test_an_engine_that_routes_and_then_adjusts_keeps_its_adjustment() -> None:
    """Check that an engine routing inside ``layout()`` keeps its later move."""
    fs, _, _ = _hung_controller()
    marker = fs.add(U.Vessel("marker"))

    class Engine:
        def layout(self, fs: Flowsheet) -> None:
            fs.layout()
            fs.route()
            assert marker.frame is not None
            marker.frame.x = marker.frame.y = 1200

    fs.layout(Engine())
    fs.route()

    assert marker.frame is not None
    assert (marker.frame.x, marker.frame.y) == (1200, 1200)


def _valve_variants() -> list[str]:
    """Return every registered valve variant."""
    from pandid.render.symbols import default_registry

    return sorted(v for kind, v in default_registry._symbols if kind == "valve")


def test_no_valve_variant_draws_its_actuator_inside_the_body():
    """Check that every valve variant draws its actuator at its routing anchor."""
    from pandid.geometry import Frame
    from pandid.portgeom import resolve_port, resolve_size

    inside = []
    for variant in _valve_variants():
        valve = U.Valve("V-1", variant=variant)
        w, h = resolve_size(valve)
        drawn = resolve_port(valve, Frame(x=0.0, y=0.0, w=w, h=h), "actuator")
        if drawn.point != drawn.anchor:
            inside.append(variant)
    assert inside == []


def test_flipping_a_valve_turns_its_actuator_over_with_it():
    """Check that mirroring a valve top to bottom moves its actuator to the far face."""
    from pandid.portgeom import port_faces

    for variant in _valve_variants():
        valve = U.Valve("V-1", variant=variant).pin(mirrored="y")
        # The PSV's pilot connection is on the side of its bonnet, and a
        # top-to-bottom flip leaves an east face where it was.
        want = "E" if variant == "relief" else "S"
        assert port_faces(valve, "actuator") == [want], variant


def test_relief_valve_is_tagged_as_plain_text_beside_the_symbol():
    fs = Flowsheet("psv")
    drum = fs.add(U.Vessel("V-101")).pin(x=200, y=100)
    psv = fs.add(U.Valve("PSV-308", variant="relief")).pin(x=221, y=20)
    flare = fs.add(U.Product("Flare")).pin(x=400, y=25)
    fs.connect(drum.vent, psv.inlet)
    fs.connect(psv.outlet, flare.inlet)
    svg = fs.to_svg()
    assert ">PSV-308<" in svg  # the whole tag, not letters over a number
    assert psv.frame.label_pos in ("left", "right")  # beside the symbol


def test_hanger_is_not_drawn_where_a_signal_already_joins_the_pair():
    fs, _, ft, _ = _line(at=0.5, offset=60)
    # sensing= and not near=, deliberately: what this asserts is that the
    # *signal* is what suppresses the hanger, so the balloon has to be one
    # that would otherwise be joined to its host by a line.
    fic = fs.add_instrument(
        "FIC", 101, sensing=ft, face="N", offset=110, angle=35, display="central"
    )
    fs.connect(ft.sig_out, fic.sig_in, kind="electric")
    # Count only lines that start a text line; a balloon's own bar is nested in its symbol.
    taps = [
        ln
        for ln in fs.to_svg().split("\n")
        if ln.strip().startswith("<line") and 'stroke-width="1"' in ln
    ]
    assert len(taps) == 1  # the transmitter's impulse line, not a second FT-FIC line


def test_interlock_hangs_off_its_controller_on_a_dashed_line():
    fs, _, ft, _ = _line(at=0.5, offset=60)
    fs.add_instrument("I", 1, sensing=ft, face="S", offset=44, variant="logic")
    taps = [ln for ln in fs.to_svg().split("\n") if "<line" in ln and 'stroke-width="1"' in ln]
    assert any("stroke-dasharray" in ln for ln in taps)  # instrument host -> dashed
    assert any("stroke-dasharray" not in ln for ln in taps)  # process tap -> solid


# --- what decides an impulse line from a functional connection ---------------


def _tap_styles(fs) -> dict:
    """Return ``"solid"`` or ``"dashed"`` for each balloon's tap line, by balloon name."""
    import re

    body = fs.to_svg().split('<g id="instrument_taps">', 1)
    if len(body) == 1:
        return {}
    from pandid.render.svg import tap_lines

    lines = re.findall(r"<(?:line|path) [^>]*/>", body[1].split("</g>", 1)[0])
    assert len(lines) == len(tap_lines(fs))
    return {
        u.name: ("dashed" if "stroke-dasharray" in ln else "solid")
        for (u, _, _), ln in zip(tap_lines(fs), lines)
    }


@pytest.mark.parametrize(
    "variant,display,style",
    [
        # A bare balloon is ISA-5.1's field-mounted device, and a device in the
        # field is the only thing a length of impulse tubing can reach.
        ("default", "field", "solid"),
        # Everything else is a location or function symbol, and says outright that
        # the function is not out on the plant: a bar across the balloon puts it in
        # a control room, a square around it in the shared display, a hexagon in a
        # computer and a diamond in a logic solver. No tubing runs from a drum to
        # any of those, whatever the drum is.
        ("default", "central", "dashed"),
        ("default", "subsidiary", "dashed"),
        ("shared", "central", "dashed"),
        ("computer", "field", "dashed"),
        ("sis", "field", "dashed"),
        ("logic", "field", "dashed"),
        ("interlock", "field", "dashed"),
    ],
)
def test_link_style_follows_the_balloon_not_only_its_host(variant, display, style):
    """Check that one host's tap line style follows the balloon's symbol and display."""
    fs = Flowsheet("what is on the end of it")
    drum = fs.add(U.Vessel("V-101")).pin(x=200, y=200)
    fs.add_instrument(
        "LX", 101, sensing=drum, face="E", offset=80, variant=variant, display=display
    )
    fs.route()
    assert _tap_styles(fs) == {"LX-101": style}


@pytest.mark.parametrize(
    "host,style",
    [
        # A pipe and a vessel are both full of the fluid the reading is taken from.
        ("stream", "solid"),
        ("vessel", "solid"),
        # A valve is too -- and this is the case the host's class got wrong. What
        # makes the line off it a signal is the *square*, not the valve.
        ("valve", "solid"),
        # A balloon holds nothing, and a signal line holds a command.
        ("instrument", "dashed"),
        ("signal", "dashed"),
    ],
)
def test_link_style_follows_the_host_not_only_its_balloon(host, style):
    """Check that one field balloon's tap line style follows its host."""
    fs = Flowsheet("what it comes off")
    feed = fs.add(U.Feed("Feed")).pin(x=60, y=170)
    drum = fs.add(U.Vessel("V-101")).pin(x=400, y=140)
    line = fs.connect(feed.outlet, drum.inlet)
    hosts = {"stream": lambda: (line, {"at": 0.5}), "vessel": lambda: (drum, {"face": "S"})}
    if host == "valve":
        valve = fs.add(U.Valve("XV-1", variant="solenoid")).pin(x=200, y=300)
        hosts["valve"] = lambda: (valve, {"face": "S"})
    elif host in ("instrument", "signal"):
        lt = fs.add_instrument("LT", 101, sensing=drum, face="E", offset=70)
        lic = fs.add_instrument("LIC", 101, near=lt, face="E", offset=70, variant="shared")
        signal = fs.connect(lt.sig_out, lic.sig_in, kind="electric")
        hosts["instrument"] = lambda: (lt, {"face": "N"})
        hosts["signal"] = lambda: (signal, {"at": 0.5})
    anchor, where = hosts[host]()
    fs.add_instrument("PX", 1, sensing=anchor, offset=70, variant="default", **where)
    fs.route()
    assert _tap_styles(fs)["PX-1"] == style


def test_the_trip_square_on_a_valve_is_drawn_as_the_signal_it_is():
    """Check that a trip square on a valve is dashed while a gauge on it stays solid."""
    fs = Flowsheet("one function, five drawings")
    feed = fs.add(U.Feed("Feed")).pin(x=60, y=170)
    xv = fs.add(U.Valve("XV-301", variant="solenoid")).pin(x=250, port="inlet", y=195)
    prod = fs.add(U.Product("Product")).pin(x=520, y=170)
    fs.connect(feed.outlet, xv.inlet)
    fs.connect(xv.outlet, prod.inlet)
    ti = fs.add_instrument("TI", 325, sensing=xv, face="N", offset=44)
    fs.add_instrument("I", 2, acting_on=xv, face="S", offset=44, variant="sis")
    fs.add_instrument("I", 2, sensing=ti, face="E", offset=44, variant="sis")
    fs.route()
    styles = _tap_styles(fs)
    assert styles["I-2"] == styles["I-2 (2)"] == "dashed"
    # ...and the gauge reading the same valve is still tubing, so this is not
    # the whole sheet quietly going dashed.
    assert styles["TI-325"] == "solid"


def test_balloon_signal_ports_reach_every_face():
    """Check that a balloon's signal port can be put on any of the four faces."""
    from pandid.portgeom import port_anchor

    seen = {}
    for face in ("N", "S", "E", "W"):
        fs = Flowsheet("faces")
        inst = fs.add_instrument("LIC", 101, display="central")
        inst.pin(x=200, y=250)
        inst.nozzle("sig_out", face)
        fs.layout()
        seen[face] = port_anchor(inst, inst.frame, "sig_out")[2]
    assert seen == {"N": "N", "S": "S", "E": "E", "W": "W"}


def test_balloon_ports_have_no_face_of_their_own_but_equipment_nozzles_do():
    # A balloon connection offers all four faces and owns none of them; a drum's
    # inlet offers three and owns every one, which is why authoring alternates
    # for it does not let another nozzle share them.
    from pandid.render.symbols import default_registry

    balloon = default_registry.get("instrument", "panel")
    for name in ("pv", "sig_in", "sig_out"):
        assert set(balloon.port_faces[name]) == {"N", "S", "E", "W"}
    assert balloon.faceless_ports == {"pv", "sig_in", "sig_out"}
    drum = default_registry.get("vessel", "horizontal")
    assert set(drum.port_faces["inlet"]) == {"W", "N", "E"}  # either head, or above
    assert set(drum.port_faces["outlet"]) == {"S"}
    assert not drum.faceless_ports


def test_a_barred_balloons_tag_clears_its_location_bar():
    """Check that a barred balloon writes its letters above the bar and number below."""
    import re

    from pandid.render.symbols import default_registry

    for kwargs, bars in (
        ({"display": "central"}, (22.0,)),
        ({"display": "subsidiary"}, (19.0, 25.0)),
        ({"variant": "shared"}, (22.0,)),
    ):
        fs = Flowsheet("bar")
        inst = fs.add_instrument("LIC", 101, **kwargs).pin(x=200, y=200)
        fs.layout()
        svg = fs.to_svg(check=False)
        sym = default_registry.get("instrument", inst.variant)
        # Balloon centre in sheet coordinates, and the bars relative to it.
        cy = inst.frame.y + inst.frame.h / 2
        band = [cy + b - sym.height / 2 for b in bars]

        ys = {
            t: float(y)
            for y, t in re.findall(r'<text x="[\d.]+" y="([\d.]+)"[^>]*>(LIC|101)</text>', svg)
        }
        assert len(ys) == 2, f"{inst.variant}: expected both tag lines, got {ys}"
        # 12pt letters and an 11pt number, centred on their baselines.
        assert ys["LIC"] + 6 <= min(band), f"{inst.variant}: letters run into the bar"
        assert ys["101"] - 5.5 >= max(band), f"{inst.variant}: number runs into the bar"


def test_every_shared_display_balloon_carries_a_location_bar():
    """Check that the shared display balloon draws a bar across the circle's diameter."""
    import re

    from pandid.render.symbols import default_registry

    sym = default_registry.get("instrument", "shared")
    circle = re.search(r'<circle cx="([\d.]+)" cy="([\d.]+)" r="([\d.]+)"', sym.svg)
    bar = re.search(r'<line x1="([\d.]+)" y1="([\d.]+)" x2="([\d.]+)" y2="([\d.]+)"', sym.svg)
    assert bar, "the shared balloon draws a location bar"
    cx, cy, r = (float(g) for g in circle.groups())
    x1, y1, x2, y2 = (float(g) for g in bar.groups())
    assert y1 == y2 == cy, "horizontal, on the circle's centre line"
    assert (x1, x2) == (cx - r, cx + r), "and the circle's full diameter"
    # And the square is still there: the bar is an addition, not a replacement.
    assert "<rect" in sym.svg


def test_a_short_pneumatic_run_still_gets_its_cross_hatch():
    """Check that a short pneumatic run still gets its cross-hatch."""
    fs = Flowsheet("short-pneumatic")
    valve = fs.add(U.Valve("LV-101", variant="control")).pin(x=300, y=300)
    ly = fs.add_instrument("LY", 101, near=valve, face="N", offset=58)
    ly.nozzle("sig_out", "S")
    fs.connect(ly.sig_out, valve.actuator, kind="pneumatic")
    fs.layout()

    from pandid.portgeom import port_point

    run = next(s for s in fs.streams if s.kind == "pneumatic")
    points = (
        [port_point(ly, ly.frame, "sig_out")]
        + (run.route.waypoints if run.route and run.route.waypoints else [])
        + [port_point(valve, valve.frame, "actuator")]
    )
    length = sum(abs(b[0] - a[0]) + abs(b[1] - a[1]) for a, b in zip(points, points[1:]))
    assert 16 <= length < 45, f"specimen must be a *short* run, got {length}"
    # Two strokes per mark, and the sheet carries exactly the one signal.
    assert _hatch_marks(fs.to_svg(check=False)) >= 2


# --- a tag that repeats, and one that must not --------------------------------


def _interlocked(n=4):
    """Return one trip square acting on ``n`` valves, drawn beside each."""
    fs = Flowsheet("interlock")
    pairs = []
    for i in range(n):
        valve = fs.add(U.Valve(f"XV-{i + 1}", variant="control")).pin(x=200 + 260 * i, y=400)
        square = fs.add(U.Instrument("I", 1, variant="logic")).pin(x=210 + 260 * i, y=250)
        fs.connect(square.sig_out, valve.actuator, kind="electric")
        pairs.append((square, valve))
    return fs, pairs


def test_an_interlock_square_is_drawn_at_every_place_it_acts():
    """Check that one interlock square is drawn at each of four valves under one tag."""
    fs, pairs = _interlocked()
    squares = [square for square, _ in pairs]
    assert [s.tag for s in squares] == ["I-1"] * 4
    assert [s.name for s in squares] == ["I-1", "I-1 (2)", "I-1 (3)", "I-1 (4)"]


def test_each_repeated_square_is_still_one_unit_to_look_up():
    """Check that each repeated square has its own name and its own valve."""
    fs, pairs = _interlocked()
    for square, valve in pairs:
        assert [u for u in fs.units if u.name == square.name] == [square]
        assert square.sig_out.stream.dest.owner is valve


def test_the_repeated_square_draws_the_tag_it_shares():
    """Check that each repeated square draws the shared number and not its name."""
    fs, _ = _interlocked()
    svg = fs.to_svg()
    assert svg.count(">1</text>") == 4
    assert "(2)" not in svg


def test_a_repeated_square_survives_a_round_trip_through_a_spec():
    """Check that repeated squares round-trip through the spec with their wiring."""
    fs, _ = _interlocked()
    spec = fs.to_dict()
    rebuilt = Flowsheet.from_dict(spec)
    assert sorted(u.name for u in rebuilt.units) == sorted(u.name for u in fs.units)
    assert [(s.source.owner.name, s.dest.owner.name) for s in rebuilt.streams] == [
        (s.source.owner.name, s.dest.owner.name) for s in fs.streams
    ]
    assert rebuilt.to_dict() == spec


# --- the signal pool: several connections on one balloon ----------------------


def _split_range():
    """Return loop 301: one controller on two control valves, pinned."""
    fs = Flowsheet("split range")
    loop = fs.add_loop("P", 301)
    pt = fs.add(U.Instrument("PT", 301)).pin(x=120, y=300)
    pic = fs.add(U.Instrument("PIC", 301, variant="shared")).pin(x=340, y=300)
    cv1 = fs.add(U.Valve("CV-301-1", variant="control")).pin(x=320, y=520)
    cv2 = fs.add(U.Valve("CV-301-2", variant="control")).pin(x=600, y=280)
    fs.connect(pt.sig_out, pic.sig_in, kind="electric")
    lo = fs.connect(pic.sig_out, cv1.actuator, kind="pneumatic")
    hi = fs.connect(pic.sig_out, cv2.actuator, kind="pneumatic")
    return fs, loop, pt, pic, (cv1, lo), (cv2, hi)


def test_split_range_draws_one_controller_onto_two_valves():
    """Check that one controller draws two outputs onto two valve stems."""
    from pandid.portgeom import port_point

    fs, _, _, pic, (cv1, lo), (cv2, hi) = _split_range()
    assert lo.source.owner is pic and lo.dest is cv1.actuator
    assert hi.source.owner is pic and hi.dest is cv2.actuator
    assert lo.source is not hi.source
    fs.route()
    # Two lines off one balloon leave from two different points on it, which is
    # the whole of what "several connections, on any face" has to mean.
    assert port_point(pic, pic.frame, lo.source.name) != port_point(pic, pic.frame, hi.source.name)
    svg = fs.to_svg()
    assert ">PIC<" in svg and ">301<" in svg
    assert svg.count("<path") >= 3  # the measurement and both outputs


def test_a_second_line_off_one_output_is_another_connection():
    """Check that a second line off ``sig_out`` mints ``sig_out_2`` and leaves the first."""
    _, _, _, pic, (_, lo), (_, hi) = _split_range()
    assert lo.source is pic.sig_out
    assert pic.sig_out.stream is lo
    assert hi.source.name == "sig_out_2"
    assert list(pic.ports) == ["pv", "sig_in", "sig_out", "sig_out_2"]


def test_a_balloon_with_one_line_each_way_grows_nothing():
    """Check that a balloon with one line each way keeps its three ports."""
    fs = Flowsheet("plain")
    a = fs.add(U.Instrument("FT-101"))
    b = fs.add(U.Instrument("FIC-101", display="central"))
    fs.connect(a.sig_out, b.sig_in, kind="electric")
    assert list(a.ports) == ["pv", "sig_in", "sig_out"]
    assert list(b.ports) == ["pv", "sig_in", "sig_out"]


def test_a_minted_connection_is_drawn_on_the_balloons_own_nozzle():
    """Check that a minted port is anchored and offers the pool's four faces."""
    from pandid.portgeom import is_anchored, port_faces

    _, _, _, pic, _, _ = _split_range()
    assert is_anchored(pic, "sig_out_2")
    assert set(port_faces(pic, "sig_out_2")) == set(port_faces(pic, "sig_out"))
    assert set(port_faces(pic, "sig_out_2")) == {"N", "S", "E", "W"}


def test_each_output_takes_a_face_of_its_own():
    """Check that a balloon's three connections resolve to three faces."""
    from pandid.portgeom import resolve_port
    from pandid.validate import validate

    fs, _, _, pic, _, _ = _split_range()
    fs.route()
    faces = {
        name: resolve_port(pic, pic.frame, name).face for name in ("sig_in", "sig_out", "sig_out_2")
    }
    assert len(set(faces.values())) == 3, faces
    assert not [i for i in validate(fs) if i.code == "coincident-ports"]


def test_a_measurement_feeds_two_alarms_on_separate_lines():
    """Check that a measurement feeding two alarms takes two outputs."""
    fs = Flowsheet("alarms")
    li = fs.add(U.Instrument("LI", 322, variant="shared")).pin(x=200, y=300)
    lah = fs.add(U.Instrument("LAH", 322, variant="shared")).pin(x=420, y=200)
    lal = fs.add(U.Instrument("LAL", 322, variant="shared")).pin(x=420, y=400)
    high = fs.connect(li.sig_out, lah.sig_in, kind="electric")
    low = fs.connect(li.sig_out, lal.sig_in, kind="electric")
    assert high.source is not low.source
    assert {high.source.name, low.source.name} == {"sig_out", "sig_out_2"}
    fs.route()
    assert fs.to_svg()


def test_an_alarm_takes_an_input_and_an_output():
    """Check that an alarm takes a line in and a line out."""
    fs = Flowsheet("trip")
    lt = fs.add(U.Instrument("LT", 322)).pin(x=120, y=300)
    lal = fs.add(U.Instrument("LAL", 322, variant="shared")).pin(x=360, y=300)
    trip = fs.add(U.Instrument("I", 1, variant="sis")).pin(x=600, y=300)
    fs.connect(lt.sig_out, lal.sig_in, kind="electric")
    fs.connect(lal.sig_out, trip.sig_in, kind="electric")
    assert lal.sig_in.stream.source.owner is lt
    assert lal.sig_out.stream.dest.owner is trip


def test_a_signal_connection_takes_either_end_of_its_line():
    """Check that a signal port may be either end of a signal line."""
    fs = Flowsheet("either end")
    a = fs.add(U.Instrument("LAL-322", variant="shared"))
    b = fs.add(U.Instrument("I-1", variant="sis"))
    # ``sig_in`` as the source: named for the author's reading, not enforced.
    s = fs.connect(a.sig_in, b.sig_in, kind="electric")
    assert s.source is a.sig_in and s.dest is b.sig_in
    assert s.source.direction == "inlet"  # the field is a label, not a rule


def test_a_process_nozzle_still_has_a_direction():
    """Check that a pipe drawn against a nozzle's direction is still refused."""
    fs = Flowsheet("piping")
    p1 = fs.add(U.Pump("P-101"))
    p2 = fs.add(U.Pump("P-102"))
    with pytest.raises(ValueError, match="must be an outlet"):
        fs.connect(p1.suction, p2.discharge)
    with pytest.raises(ValueError, match="must be an inlet"):
        fs.connect(p1.discharge, p2.discharge)


def test_the_process_tap_is_one_tap():
    """Check that a second line onto an instrument's ``pv`` is refused."""
    fs = Flowsheet("tap")
    fic = fs.add(U.Instrument("FIC-301", variant="shared"))
    a = fs.add(U.Instrument("FT-301"))
    b = fs.add(U.Instrument("FT-302"))
    fs.connect(a.sig_out, fic.pv, kind="electric")
    with pytest.raises(ValueError, match=r"FIC-301\.pv is already connected"):
        fs.connect(b.sig_out, fic.pv, kind="electric")


def test_a_valve_has_one_actuator():
    """Check that a second line onto a valve's actuator is refused."""
    fs = Flowsheet("stem")
    cv = fs.add(U.Valve("CV-301-1", variant="control"))
    a = fs.add(U.Instrument("PIC-301", variant="shared"))
    b = fs.add(U.Instrument("HIC-301", variant="shared"))
    fs.connect(a.sig_out, cv.actuator, kind="pneumatic")
    with pytest.raises(ValueError, match=r"CV-301-1\.actuator is already connected"):
        fs.connect(b.sig_out, cv.actuator, kind="pneumatic")


# --- naming the units instead of their connections ----------------------------


def test_naming_the_units_draws_the_signal_line():
    """Check that naming two units on a signal line picks their signal ports."""
    fs = Flowsheet("units")
    ft = fs.add(U.Instrument("FT-305"))
    fic = fs.add(U.Instrument("FIC-305", variant="shared"))
    cv = fs.add(U.Valve("CV-305", variant="control"))
    a = fs.connect(ft, fic, kind="electric")
    b = fs.connect(fic, cv, kind="pneumatic")
    assert (a.source.name, a.dest.name) == ("sig_out", "sig_in")
    assert (b.source.name, b.dest.name) == ("sig_out", "actuator")


def test_naming_the_units_mints_a_second_output():
    """Check that naming a controller twice mints its second output."""
    fs = Flowsheet("units split")
    pic = fs.add(U.Instrument("PIC-301", variant="shared"))
    cv1 = fs.add(U.Valve("CV-301-1", variant="control"))
    cv2 = fs.add(U.Valve("CV-301-2", variant="control"))
    fs.connect(pic, cv1, kind="pneumatic")
    fs.connect(pic, cv2, kind="pneumatic")
    assert list(pic.ports) == ["pv", "sig_in", "sig_out", "sig_out_2"]


def test_piping_still_names_its_nozzle():
    """Check that a process line between bare units is refused."""
    fs = Flowsheet("piping")
    p1 = fs.add(U.Pump("P-101"))
    p2 = fs.add(U.Pump("P-102"))
    with pytest.raises(ValueError, match="a unit rather than one of its nozzles"):
        fs.connect(p1, p2)


def test_a_unit_with_no_signal_connection_is_named_not_guessed_at():
    """Check that naming a unit with no signal port is refused."""
    fs = Flowsheet("no stem")
    pic = fs.add(U.Instrument("PIC-301", variant="shared"))
    pump = fs.add(U.Pump("P-101"))
    with pytest.raises(ValueError, match="has no signal connection"):
        fs.connect(pic, pump, kind="electric")


def test_a_unit_with_several_signal_connections_is_not_guessed_at():
    """Check that naming a unit with two signal ports outside a pool is refused."""
    fs = Flowsheet("ambiguous")
    pic = fs.add(U.Instrument("PIC-301", variant="shared"))
    station = fs.add(U.Valve("CV-301", variant="control"))
    station._add_port("sig_spare", "inlet", "signal")
    with pytest.raises(ValueError, match="2 signal connections"):
        fs.connect(pic, station, kind="pneumatic")


def test_split_range_survives_a_round_trip_through_a_spec():
    """Check that a minted port round-trips through the spec."""
    fs, *_ = _split_range()
    spec = fs.to_dict()
    rebuilt = Flowsheet.from_dict(spec)
    pic = next(u for u in rebuilt.units if u.name == "PIC-301")
    assert list(pic.ports) == ["pv", "sig_in", "sig_out", "sig_out_2"]
    assert rebuilt.to_dict() == spec


def test_a_refused_connection_mints_nothing():
    """Check that a refused connection mints no port."""
    fs = Flowsheet("refused")
    pic = fs.add(U.Instrument("PIC-301", variant="shared"))
    cv = fs.add(U.Valve("CV-301-1", variant="control"))
    fs.connect(pic.sig_out, cv.actuator, kind="pneumatic")
    with pytest.raises(ValueError, match="already connected"):
        fs.connect(pic.sig_out, cv.actuator, kind="pneumatic")  # same valve twice
    assert list(pic.ports) == ["pv", "sig_in", "sig_out"]
    with pytest.raises(ValueError, match="signal connection"):
        fs.connect(pic.sig_out, fs.add(U.Pump("P-101")).suction, kind="pneumatic")
    assert list(pic.ports) == ["pv", "sig_in", "sig_out"]


def _crowded(variant: str, outputs: int) -> tuple[Flowsheet, U.Instrument]:
    """Return a pinned controller with a measurement in and ``outputs`` valves out."""
    fs = Flowsheet("crowded")
    pic = fs.add(U.Instrument("PIC-301", variant=variant)).pin(x=400, y=400)
    pt = fs.add(U.Instrument("PT-301")).pin(x=100, y=400)
    fs.connect(pt.sig_out, pic.sig_in, kind="electric")
    for i in range(outputs):
        cv = fs.add(U.Valve(f"CV-{i}", variant="control")).pin(x=100 + 180 * i, y=700)
        fs.connect(pic.sig_out, cv.actuator, kind="pneumatic")
    fs.route()
    return fs, pic


@pytest.mark.parametrize("outputs", [2, 6])
@pytest.mark.parametrize("variant", ["default", "shared", "computer", "sis", "interlock"])
def test_each_line_off_a_balloon_leaves_from_its_own_point(variant: str, outputs: int):
    """Check that every line off a crowded balloon has a point of its own."""
    from pandid.validate import validate

    fs, pic = _crowded(variant, outputs)
    points = [port_point(pic, frame_of(pic), n) for n, p in pic.ports.items() if p.stream]
    assert len(points) == outputs + 1
    assert len(set(points)) == len(points)
    assert [i.code for i in validate(fs) if i.severity == "error"] == []


def test_lines_sharing_a_face_of_a_balloon_meet_its_circle():
    """Check that lines sharing a face of a round balloon end on its circle."""
    _, pic = _crowded("default", 6)
    frame = frame_of(pic)
    for name, port in pic.ports.items():
        if port.stream is not None:
            x, y = port_point(pic, frame, name)
            assert math.hypot(x - frame.cx, y - frame.cy) == pytest.approx(21.5, abs=0.6)


def test_lines_sharing_a_face_of_a_wide_balloon_meet_its_circle():
    """Check that lines sharing a face of a balloon in a wide box end on its circle."""
    fs = Flowsheet("wide")
    pic = fs.add(U.Instrument("PIC-1", width=200, height=44)).pin(x=400, y=400)
    for i in range(6):
        cv = fs.add(U.Valve(f"CV-{i}", variant="control")).pin(x=100 + 180 * i, y=700)
        pic.nozzle(fs.connect(pic, cv.actuator, kind="pneumatic").source.name, "S")
    fs.route()
    frame = frame_of(pic)
    for name, port in pic.ports.items():
        if port.stream is not None:
            x, y = port_point(pic, frame, name)
            assert math.hypot(x - frame.cx, y - frame.cy) == pytest.approx(21.5, abs=0.6)


@pytest.mark.parametrize("outputs", [2, 6])
def test_a_balloon_pinned_by_its_output_draws_that_output_on_the_pin(outputs: int):
    """Check that the output a balloon is pinned by stays on the pin."""
    fs = Flowsheet("pinned")
    pic = fs.add(U.Instrument("PIC-1")).pin(port="sig_out", x=600, y=400)
    for i in range(outputs):
        feed = fs.add(U.Feed(f"F-{i}"))
        cv = fs.add(U.Valve(f"CV-{i}", variant="control")).pin(x=1000, y=200 + 80 * i)
        fs.connect(feed.outlet, cv.inlet)
        fs.connect(cv.outlet, fs.add(U.Product(f"P-{i}")).inlet)
        fs.connect(pic, cv.actuator, kind="pneumatic")
    fs.route()
    assert port_point(pic, frame_of(pic), "sig_out") == (600, 400)
    points = [port_point(pic, frame_of(pic), n) for n, p in pic.ports.items() if p.stream]
    assert len(set(points)) == outputs
    assert [i.code for i in fs.validate() if i.severity == "error"] == []


def test_outputs_past_four_share_the_face_toward_their_valves_in_their_order():
    """Check that extra outputs join the face toward their valves, top to bottom."""
    from pandid.portgeom import resolve_port

    fs = Flowsheet("west")
    pic = fs.add(U.Instrument("PIC-301")).pin(x=600, y=400)
    pt = fs.add(U.Instrument("PT-301")).pin(x=900, y=400)
    fs.connect(pt.sig_out, pic.sig_in, kind="electric")
    for i in range(6):
        cv = fs.add(U.Valve(f"CV-{i}", variant="control")).pin(x=100, y=650 - 100 * i)
        fs.connect(pic.sig_out, cv.actuator, kind="pneumatic")
    fs.route()
    ends = {
        frame_of(p.stream.dest.owner).cy: resolve_port(pic, frame_of(pic), name)
        for name, p in pic.ports.items()
        if p.stream is not None and p.stream.source is p
    }
    assert "E" not in {end.face for end in ends.values()}
    west = [end.point[1] for _, end in sorted(ends.items()) if end.face == "W"]
    assert len(west) > 1 and west == sorted(west)


def test_a_pool_member_can_be_asked_for_by_name():
    """Check that ``signal_port`` mints a pool member once and refuses an unknown pool."""
    fs = Flowsheet("by name")
    pic = fs.add(U.Instrument("PIC-301", variant="shared"))
    port = pic.signal_port("sig_out_2")
    assert port.name == "sig_out_2" and port.role == "signal"
    assert pic.signal_port("sig_out_2") is port  # asked twice, minted once
    assert pic.signal_port("sig_out") is pic.sig_out
    with pytest.raises(KeyError, match="signal pools"):
        pic.signal_port("sig_sideways")


# --- what the balloon has to do with what it is placed against ----------------


def _drum(relation, **kwargs):
    """Return one balloon on one drum, placed by the named relation keyword."""
    fs = Flowsheet("relation")
    feed = fs.add(U.Feed("Feed")).pin(x=60, y=170)
    drum = fs.add(U.Vessel("V-101")).pin(x=300, y=140)
    prod = fs.add(U.Product("Product")).pin(x=600, y=170)
    fs.connect(feed.outlet, drum.inlet)
    fs.connect(drum.outlet, prod.inlet)
    inst = fs.add_instrument("LX", 101, face="E", offset=70, **{relation: drum}, **kwargs)
    fs.route()
    return fs, inst


def test_a_placement_draws_nothing_where_a_reading_draws_a_line():
    """Check that ``near=`` draws no tap line where ``sensing=`` draws one."""
    from pandid.render.svg import tap_lines

    read, reading = _drum("sensing")
    stood, standing = _drum("near")
    assert [u.name for u, _, _ in tap_lines(read)] == ["LX-101"]
    assert tap_lines(stood) == []
    assert (reading.relation, standing.relation) == ("sensing", "near")
    # ...and the group is not merely empty, it is not opened at all.
    assert '<g id="instrument_taps">' in read.to_svg()
    assert '<g id="instrument_taps">' not in stood.to_svg()


@pytest.mark.parametrize(
    ("case", "corners"),
    [("pipe", 1), ("face", 1), ("behind", 2), ("level", 3), ("near", 1), ("opposite", 3)],
)
def test_a_balloon_off_its_taps_axis_is_reached_square(case: str, corners: int) -> None:
    """Check that an off-axis balloon's tap line turns square and clears the unit."""
    import xml.etree.ElementTree as ET

    from pandid.portgeom import unit_box
    from pandid.render.svg import tap_lines

    fs = Flowsheet("dogleg")
    feed = fs.add(U.Feed("Feed")).pin(x=60, y=170)
    drum = fs.add(U.Vessel("V-101")).pin(x=300, y=140)
    prod = fs.add(U.Product("Product")).pin(x=600, y=170)
    line = fs.connect(feed.outlet, drum.inlet)
    fs.connect(drum.outlet, prod.inlet)
    if case == "pipe":
        fs.add_instrument("PI", 101, at=0.5, offset=60, angle=45, sensing=line)
    elif case == "face":
        fs.add_instrument("LX", 101, face="S", offset=70, angle=45, sensing=drum)
    elif case == "behind":
        fs.add_instrument("LX", 101, face="S", sensing=drum).pin(x=420, y=150)
    elif case == "level":
        fs.add_instrument("LX", 101, face="E", sensing=drum).pin(x=120, y=150)
    elif case == "near":
        fs.add_instrument("LX", 101, face="E", sensing=drum).pin(x=420, y=168.25)
    else:
        fs.add_instrument("LX", 101, face="E", sensing=drum).pin(x=120, y=168)
    fs.route()
    ((_, tap, centre),) = tap_lines(fs)
    group = fs.to_svg().split('<g id="instrument_taps">', 1)[1].split("</g>", 1)[0]
    drawn = ET.fromstring(group.strip())
    d = drawn.get("d") or "M {x1},{y1} L {x2},{y2}".format(**drawn.attrib)
    points = [tuple(float(v) for v in p.split(",")) for p in d[2:].split(" L ")]
    assert len(points) == corners + 2, f"{case}: drawn {points}"
    left, top, right, bottom = unit_box(drum, drum.frame)
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        assert x1 == x2 or y1 == y2, f"{case}: drawn {points}"
        inside = min(x1, x2) < right and max(x1, x2) > left
        assert not (inside and min(y1, y2) < bottom and max(y1, y2) > top), (
            f"{case}: drawn {points}"
        )
    assert points[0] == pytest.approx(tap, abs=0.01)
    assert points[-1] == pytest.approx(centre, abs=0.01)
    # draw.io gets the same corners as waypoints.
    edge = fs.to_drawio().split('id="t0"', 1)[1].split("</mxCell>", 1)[0]
    assert edge.split('<Array as="points">', 1)[1].count("<mxPoint ") == corners


def test_a_balloon_on_a_slanted_pipe_is_reached_square() -> None:
    """A balloon on a manually slanted run is reached with one square turn."""
    from pandid.render.svg import tap_lines, tap_route

    fs = Flowsheet("slant")
    feed = fs.add(U.Feed("Feed")).pin(x=100, y=100)
    prod = fs.add(U.Product("Product")).pin(x=500, y=500)
    line = fs.connect(feed.outlet, prod.inlet)
    line.via([(200, 200), (400, 400)])
    fs.add_instrument("PI", 101, sensing=line, at=0.5).pin(x=578, y=578)
    fs.to_svg()
    fs.to_drawio()
    ((inst, tap, centre),) = tap_lines(fs)
    route = tap_route(inst, tap, centre)
    assert len(route) == 3
    for (x1, y1), (x2, y2) in zip(route, route[1:]):
        assert x1 == x2 or y1 == y2, route


def test_a_placement_is_still_a_placement():
    """Check that ``near=`` still hangs the balloon off the face it names."""
    _, standing = _drum("near")
    host = standing.host
    assert standing.face == "E"
    assert (standing.frame.cx, standing.frame.cy) == pytest.approx(
        (host.frame.x_max + 70, host.frame.cy)
    )


def test_a_command_is_a_signal_even_where_the_host_holds_fluid():
    """Check that ``acting_on=`` a vessel draws a dashed line, not tubing."""
    from pandid.render.svg import impulse_tap

    _, reading = _drum("sensing")
    fs, commanding = _drum("acting_on")
    assert impulse_tap(reading) is True
    assert impulse_tap(commanding) is False
    # Both are drawn: what differs is what the line says, not whether there is
    # one. A command reaches what it acts on, and the sheet has to show it.
    assert _tap_styles(fs) == {"LX-101": "dashed"}


def test_a_balloon_is_placed_against_one_thing():
    """Check that naming two relation keywords is refused with both named."""
    fs = Flowsheet("two anchors")
    drum = fs.add(U.Vessel("V-101"))
    valve = fs.add(U.Valve("FV-101", variant="control"))
    with pytest.raises(ValueError) as excinfo:
        fs.add_instrument("LX", 101, sensing=drum, near=valve)
    message = str(excinfo.value)
    assert "named 2 (sensing=, near=)" in message
    assert "connect()" in message  # ...and where a second relationship goes


def test_an_unknown_relation_is_refused_at_the_call_that_wrote_it():
    from pandid.units import RELATIONS

    fs = Flowsheet("relation")
    drum = fs.add(U.Vessel("V-101"))
    with pytest.raises(ValueError, match="relation="):
        fs.add(U.Instrument("LX", 101)).attach(drum, relation="watching")
    assert RELATIONS == ("sensing", "acting_on", "near")


# --- two axes: what the instrument does, and where its reading is -------------


@pytest.mark.parametrize(
    "display,drawn", [("field", "default"), ("central", "panel"), ("subsidiary", "aux")]
)
def test_a_display_picks_the_artwork_its_bar_is_drawn_in(display, drawn):
    """Check that each display picks its registered balloon variant."""
    inst = U.Instrument("LIC", 101, display=display)
    assert (inst.symbol_type, inst.display, inst.variant) == ("default", display, drawn)


def test_a_square_says_where_it_is_without_being_asked():
    """Check that the shared square's display is central and its variant kept."""
    shared = U.Instrument("FIC", 301, variant="shared")
    assert (shared.variant, shared.display) == ("shared", "central")
    assert U.Instrument("FIC", 301, variant="shared", display="central").variant == "shared"


def test_a_display_is_registered_artwork_and_not_a_stripe_over_any_outline():
    """Check that an unregistered symbol and display pair is refused, naming those that are."""
    with pytest.raises(ValueError) as excinfo:
        U.Instrument("KIC", 301, variant="computer", display="central")
    message = str(excinfo.value)
    assert "no balloon is drawn for variant='computer' with display='central'" in message
    # ...and it names the pairs that are drawn, so the reader has somewhere to go
    assert "variant='default' display='central'" in message
    assert "variant='default' display='subsidiary'" in message
    assert "variant='shared' display='central'" in message


def test_a_display_that_is_not_one_of_the_three_is_refused():
    with pytest.raises(ValueError, match="display= is where the information"):
        U.Instrument("LIC", 101, display="panel")


# --- letter codes written outside the symbol ----------------------------------


def test_annotate_writes_high_and_low_into_the_quadrants_iso_names_them():
    """Check that ``annotate`` writes high codes into quadrant c and low into d."""
    inst = U.Instrument("LIC", 304)
    assert inst.annotate(high="LAH", low="LAL") is inst
    written = {name: codes for name, codes in inst.quadrants.items() if codes}
    assert written == {"c": ("LAH",), "d": ("LAL",)}


def test_several_codes_in_one_quadrant_take_the_sequence_the_standard_fixes():
    """Check that codes in one quadrant are ordered A, S, Z however they are given."""
    scrambled = U.Instrument("LIC", 304).annotate(high=("LZHH", "LAHH", "LSHH"))
    in_order = U.Instrument("LIC", 305).annotate(high=("LAHH", "LSHH", "LZHH"))
    assert scrambled.quadrants["c"] == ("LAHH", "LSHH", "LZHH")
    assert in_order.quadrants["c"] == scrambled.quadrants["c"]


def test_an_empty_letter_code_is_refused_rather_than_written():
    """Check that an empty letter code is refused."""
    with pytest.raises(ValueError, match="empty letter code"):
        U.Instrument("LIC", 304).annotate(high=("LAH", ""))


def test_a_refused_annotation_leaves_every_quadrant_as_it_was():
    """Check that a refused ``annotate`` writes and clears no quadrant."""
    inst = U.Instrument("LIC", 304).annotate(safety="SIL1", variable="pH", low="LAL")
    with pytest.raises(ValueError, match="empty letter code"):
        inst.annotate(safety="SIL2", variable=(), high=["LAH", " "])
    assert inst.quadrants == {"a": ("SIL1",), "b": ("pH",), "d": ("LAL",)}


def test_an_annotated_balloon_spends_no_face():
    """Check that annotations are drawn as text and add no units."""
    fs = Flowsheet("annotated")
    lt = fs.add(U.Instrument("LT-304")).pin(x=200, y=400)
    lic = fs.add(U.Instrument("LIC-304", variant="shared")).pin(x=200, y=250)
    lic.annotate(high="LAH", low="LAL")
    fs.connect(lt.sig_out, lic.sig_in, kind="electric")
    fs.route()
    svg = fs.to_svg()
    assert ">LAH</text>" in svg and ">LAL</text>" in svg
    # Lettering, not instruments: no second balloon was drawn for either.
    assert [u.name for u in fs.units] == ["LT-304", "LIC-304"]


# --- a primary element's balloon ----------------------------------------------


def _element():
    """Return a tagged venturi in a run, with nothing else on the sheet."""
    fs = Flowsheet("primary element")
    feed = fs.add(U.Feed("Feed")).pin(x=60, y=170)
    fe = fs.add(U.Fitting("FE-303", variant="venturi")).pin(x=300, port="inlet", y=195)
    prod = fs.add(U.Product("Product")).pin(x=560, y=170)
    fs.connect(feed.outlet, fe.inlet)
    fs.connect(fe.outlet, prod.inlet)
    return fs, fe


def test_a_balloon_carries_the_elements_tag_and_the_element_stops_drawing_it():
    """Check that ``add_balloon`` moves the element's tag onto the balloon."""
    fs, fe = _element()
    balloon = fs.add_balloon(fe, face="N", offset=38)
    assert fe.balloon is balloon
    assert (balloon.tag, balloon.name) == ("FE-303", "FE-303 (2)")
    assert (fe.tag, fe.name) == ("", "FE-303")


def test_the_shared_tag_is_drawn_exactly_once():
    """Check that the element's tag is drawn once and its bookkeeping name never."""
    fs, fe = _element()
    fs.add_balloon(fe, face="N", offset=38)
    fs.route()
    svg = fs.to_svg()
    assert svg.count(">FE<") == 1 and svg.count(">303<") == 1
    assert "(2)" not in svg


def test_the_balloon_reads_the_element_it_stands_for():
    """Check that an element's balloon senses it on a solid impulse line."""
    from pandid.render.svg import impulse_tap

    fs, fe = _element()
    balloon = fs.add_balloon(fe, face="N", offset=38)
    fs.route()
    assert (balloon.host, balloon.relation) == (fe, "sensing")
    assert impulse_tap(balloon) is True
    assert _tap_styles(fs) == {"FE-303 (2)": "solid"}


def test_a_second_balloon_on_one_element_is_refused():
    """Check that a second balloon on one element is refused."""
    fs, fe = _element()
    fs.add_balloon(fe)
    with pytest.raises(ValueError, match=r"already in the balloon 'FE-303 \(2\)'"):
        fs.add_balloon(fe)


def test_an_untagged_item_has_nothing_to_move():
    fs, _ = _element()
    tee = fs.add(U.Tee("TEE-1"))
    with pytest.raises(ValueError, match="draws no tag"):
        fs.add_balloon(tee)


def test_an_element_on_another_sheet_is_refused():
    fs, fe = _element()
    with pytest.raises(ValueError, match="already on this sheet"):
        Flowsheet("elsewhere").add_balloon(fe)


# --- the removed spellings ----------------------------------------------------


def test_the_anchor_no_longer_leaves_the_relationship_to_be_guessed():
    """Check that the removed ``on=`` keyword is refused."""
    fs = Flowsheet("removed")
    drum = fs.add(U.Vessel("V-101")).pin(x=300, y=140)
    with pytest.raises(TypeError, match="'on'"):
        fs.add_instrument("LX", 101, on=drum, face="E", offset=70)


@pytest.mark.parametrize("variant,display", [("panel", "central"), ("aux", "subsidiary")])
def test_a_location_is_no_longer_a_kind_of_balloon(variant, display):
    """Check that the removed ``panel`` and ``aux`` variants are refused, naming ``display=``."""
    with pytest.raises(ValueError, match=f"display={display!r}"):
        U.Instrument("LIC", 101, variant=variant)


def test_a_balloon_hung_from_a_tap_balloon_settles_off_the_tapped_line():
    """Settle a balloon chain whose asked spot lies on the tapped line.

    Routing settles, the line runs straight, and TIC keeps off it.
    """
    from pandid.layout.attach import stream_path

    fs = Flowsheet("settle")
    feed = fs.add(U.Feed("F")).pin(port="outlet", x=100, y=300)
    prod = fs.add(U.Product("P")).pin(port="inlet", x=600, y=300)
    line = fs.connect(feed.outlet, prod.inlet)
    tt = fs.add_instrument("TT", 1, sensing=line, offset=70)
    tic = fs.add_instrument("TIC", 1, near=tt, face="S", offset=70)
    fs.connect(tt.sig_out, tic.sig_in, kind="electric")
    fs.route()

    assert fs.route_converged
    points = stream_path(line)
    assert {y for _, y in points} == {300.0}, points
    assert tic.frame is not None
    x0, y0 = tic.frame.x, tic.frame.y
    x1, y1 = x0 + tic.frame.w, y0 + tic.frame.h
    for (ax, ay), (bx, by) in zip(points, points[1:]):
        on = min(ax, bx) <= x1 and max(ax, bx) >= x0 and min(ay, by) <= y1 and max(ay, by) >= y0
        assert not on, ((ax, ay), (bx, by), (x0, y0, x1, y1))


def test_a_balloon_pinned_on_one_axis_keeps_its_asked_branch_on_the_other():
    """Keep the asked branch of a partly pinned balloon whose pinned box clears the line.

    TIC's free x is the one its asked offset and angle give.
    """
    from pandid.layout.attach import _anchor, _standoff_box
    from pandid.portgeom import resolve_size

    fs = Flowsheet("partial pin")
    feed = fs.add(U.Feed("F")).pin(port="outlet", x=100, y=300)
    prod = fs.add(U.Product("P")).pin(port="inlet", x=600, y=300)
    fs.connect(feed.outlet, prod.inlet)
    tt = fs.add_instrument("TT", 1, sensing=feed.outlet.stream, offset=70)
    tic = fs.add_instrument("TIC", 1, near=tt, face="S", offset=50, angle=45).pin(y=500)
    fs.route()

    anchor = _anchor(tic)
    assert anchor is not None and tic.frame is not None
    tap, ref = anchor
    w, h = resolve_size(tic)
    asked = _standoff_box(tap, ref, tic.offset, tic.angle, w, h)
    assert tic.frame.x == pytest.approx(asked[0])
    assert tic.frame.y == pytest.approx(500)


def test_keeping_a_chained_balloon_clear_is_dropped_when_it_adds_a_clash():
    """Keep the first drawing when keeping TIC off its line adds a clash.

    No tap line crosses a unit.
    """
    from pandid.layout.control import _flaws

    fs = Flowsheet("clash")
    feed = fs.add(U.Feed("F")).pin(port="outlet", x=100, y=200)
    prod = fs.add(U.Product("P")).pin(port="inlet", x=600, y=100)
    line = fs.connect(feed.outlet, prod.inlet)
    tt = fs.add_instrument("TT", 1, sensing=line, at=0.5, offset=70, angle=135)
    fs.add_instrument("TIC", 1, near=tt, face="E", offset=50, angle=0)
    fs.route()

    assert _flaws(fs)["tap-through-unit"] == 0


def test_an_unsettled_attempt_is_not_kept_over_an_unsettled_sheet():
    """Keep the first drawing when the keep-off attempt does not settle either.

    TT's tap lies on the final line.
    """
    from pandid.layout.attach import stream_path

    fs = Flowsheet("disconnected tap")
    feed = fs.add(U.Feed("F")).pin(port="outlet", x=100, y=400)
    prod = fs.add(U.Product("P")).pin(port="inlet", x=400, y=400)
    line = fs.connect(feed.outlet, prod.inlet)
    tt = fs.add_instrument("TT", 1, sensing=line, at=0.4, offset=70, angle=0)
    fs.add_instrument("TIC", 1, near=tt, face="E", offset=35, angle=135)
    fs.route()

    assert tt.tap is not None
    points = stream_path(line)
    assert any(
        min(ax, bx) <= tt.tap[0] <= max(ax, bx) and min(ay, by) <= tt.tap[1] <= max(ay, by)
        for (ax, ay), (bx, by) in zip(points, points[1:])
    ), (tt.tap, points)


def test_routing_again_draws_the_same_sheet():
    """Route a sheet whose keep-off attempt is kept twice, to the same drawing.

    The second route() gives the first route()'s drawing.
    """
    fs = Flowsheet("second route")
    feed = fs.add(U.Feed("F")).pin(port="outlet", x=100, y=200)
    prod = fs.add(U.Product("P")).pin(port="inlet", x=400, y=200)
    line = fs.connect(feed.outlet, prod.inlet)
    tt = fs.add_instrument("TT", 1, sensing=line, at=0.6, offset=50, angle=90)
    tic = fs.add_instrument("TIC", 1, near=tt, face="S", offset=35, angle=135)
    fs.connect(tt.sig_out, tic.sig_in, kind="electric")
    fs.route()
    first = fs.to_svg(check=False)
    fs.route()

    assert fs.to_svg(check=False) == first


def test_keeping_chained_balloons_clear_after_a_hang_adds_no_crossing():
    """Keep the hung drawing when keeping chained balloons clear adds a crossing.

    No line crosses a unit.
    """
    fs = Flowsheet("crossing")
    feed = fs.add(U.Feed("F")).pin(port="outlet", x=100, y=100)
    prod = fs.add(U.Product("P")).pin(port="inlet", x=400, y=200)
    line = fs.connect(feed.outlet, prod.inlet)
    tt = fs.add_instrument("TT", 1, sensing=line, at=0.6, offset=35, angle=0)
    fs.add_instrument("TIC", 1, near=tt, face="S", offset=70, angle=0)
    valve = fs.add(U.Valve("V", variant="control")).pin(x=400, y=100, orientation=270)
    lic = fs.add_instrument("LIC", 99)
    fs.connect(lic.sig_out, valve.actuator, kind="electric")
    fs.route()

    assert "route-crosses-unit" not in [issue.code for issue in fs.validate()]


def test_keeping_chained_balloons_clear_disconnects_no_tap():
    """Keep the first drawing when keeping chained balloons clear moves a tap off its line.

    TT-1's tap lies on the final line.
    """
    from pandid.layout.attach import stream_path

    fs = Flowsheet("two chains")
    feed = fs.add(U.Feed("F")).pin(port="outlet", x=100, y=400)
    prod = fs.add(U.Product("P")).pin(port="inlet", x=300, y=300)
    line = fs.connect(feed.outlet, prod.inlet)
    tt1 = fs.add_instrument("TT", 1, sensing=line, at=0.3, offset=70, angle=135)
    fs.add_instrument("TIC", 1, near=tt1, face="E", offset=50, angle=135)
    tt2 = fs.add_instrument("TT", 2, sensing=line, at=0.7, offset=100, angle=90)
    fs.add_instrument("TIC", 2, near=tt2, face="W", offset=100, angle=270)
    fs.route()

    assert tt1.tap is not None
    points = stream_path(line)
    assert any(
        min(ax, bx) <= tt1.tap[0] <= max(ax, bx) and min(ay, by) <= tt1.tap[1] <= max(ay, by)
        for (ax, ay), (bx, by) in zip(points, points[1:])
    ), (tt1.tap, points)


def test_a_run_that_doubles_back_is_two_runs():
    """Split a straight run where it reverses along its track.

    The excursion and its return are separate runs.
    """
    from pandid.layout.control import _straight_runs

    runs = _straight_runs(
        [(300.0, 265.0), (312.2, 265.0), (312.2, 275.0), (312.2, 265.0), (400.0, 265.0)]
    )
    assert runs == [
        ((300.0, 265.0), (312.2, 265.0)),
        ((312.2, 265.0), (312.2, 275.0)),
        ((312.2, 275.0), (312.2, 265.0)),
        ((312.2, 265.0), (400.0, 265.0)),
    ]
    assert _straight_runs([(0.0, 0.0), (0.0, 10.0), (0.0, 30.0), (5.0, 30.0)]) == [
        ((0.0, 0.0), (0.0, 30.0)),
        ((0.0, 30.0), (5.0, 30.0)),
    ]


def test_an_unsettled_hang_is_not_kept():
    """Keep the unhung drawing when hanging the controller takes a tap off its line.

    TT's tap lies on the final line.
    """
    from pandid.layout.attach import stream_path

    fs = Flowsheet("unsettled hang")
    feed = fs.add(U.Feed("F")).pin(port="outlet", x=100, y=200)
    prod = fs.add(U.Product("P")).pin(port="inlet", x=500, y=200)
    line = fs.connect(feed.outlet, prod.inlet)
    tt = fs.add_instrument("TT", 1, sensing=line, at=0.5, offset=35, angle=30)
    valve = fs.add(U.Valve("V", variant="control")).pin(x=400, y=500, orientation=180)
    lic = fs.add_instrument("LIC", 1)
    fs.connect(lic.sig_out, valve.actuator, kind="electric")
    fs.route()

    assert tt.tap is not None
    points = stream_path(line)
    assert any(
        min(ax, bx) <= tt.tap[0] <= max(ax, bx) and min(ay, by) <= tt.tap[1] <= max(ay, by)
        for (ax, ay), (bx, by) in zip(points, points[1:])
    ), (tt.tap, points)


def test_an_unsettled_hang_that_puts_the_tap_on_its_line_is_kept():
    """Keep an unsettled hang whose tap lies on its line where the unhung one does not.

    TT's tap lies on the final line.
    """
    from pandid.layout.attach import stream_path

    fs = Flowsheet("hang rollback")
    feed = fs.add(U.Feed("F")).pin(port="outlet", x=100, y=400)
    prod = fs.add(U.Product("P")).pin(port="inlet", x=400, y=100)
    line = fs.connect(feed.outlet, prod.inlet)
    tt = fs.add_instrument("TT", 1, sensing=line, at=0.6, offset=35, angle=30)
    valve = fs.add(U.Valve("V", variant="control")).pin(x=500, y=300, orientation=270)
    lic = fs.add_instrument("LIC", 1)
    fs.connect(lic.sig_out, valve.actuator, kind="electric")
    fs.route()

    assert tt.tap is not None
    points = stream_path(line)
    assert any(
        min(ax, bx) <= tt.tap[0] <= max(ax, bx) and min(ay, by) <= tt.tap[1] <= max(ay, by)
        for (ax, ay), (bx, by) in zip(points, points[1:])
    ), (tt.tap, points)


def test_a_hang_whose_taps_end_on_their_line_is_kept():
    """Keep a hang that takes a tap off its line where keeping balloons clear puts it back.

    The sheet settles with both taps on the final line.
    """
    from pandid.layout.attach import stream_path

    fs = Flowsheet("hang put right")
    feed = fs.add(U.Feed("F")).pin(port="outlet", x=100, y=100)
    prod = fs.add(U.Product("P")).pin(port="inlet", x=500, y=100)
    line = fs.connect(feed.outlet, prod.inlet)
    tt1 = fs.add_instrument("TT", 1, sensing=line, at=0.5, offset=35, angle=45)
    fs.add_instrument("TIC", 1, near=tt1, face="W", offset=50, angle=0)
    tt2 = fs.add_instrument("TT", 2, sensing=line, at=0.3, offset=70, angle=270)
    fs.add_instrument("TIC", 2, near=tt2, face="W", offset=70, angle=0)
    valve = fs.add(U.Valve("V", variant="control")).pin(x=400, y=400, orientation=270)
    lic = fs.add_instrument("LIC", 99)
    fs.connect(lic.sig_out, valve.actuator, kind="electric")
    fs.route()

    assert fs.route_converged
    points = stream_path(line)
    for tt in (tt1, tt2):
        assert tt.tap is not None
        assert any(
            min(ax, bx) <= tt.tap[0] <= max(ax, bx) and min(ay, by) <= tt.tap[1] <= max(ay, by)
            for (ax, ay), (bx, by) in zip(points, points[1:])
        ), (tt.name, tt.tap, points)
