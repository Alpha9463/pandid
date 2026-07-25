"""Instrumentation subsystem: balloons, tags, attachment, signal lines."""

import math

import pytest

from pfd import Flowsheet, units as U


def _line(**kw):
    """A left-to-right process line with a bubble tapping the middle of it."""
    fs = Flowsheet("tap")
    feed = fs.add(U.Feed("Feed")).pin(x=60, y=170)
    fv = fs.add(U.Valve("FV-101", variant="control")).pin(x=300, y=180)
    prod = fs.add(U.Product("Product")).pin(x=520, y=170)
    s = fs.connect(feed.outlet, fv.inlet)
    fs.connect(fv.outlet, prod.inlet)
    inst = fs.add_instrument("FT", 101, on=s, **kw)
    fs.route()
    return fs, s, inst, fv


def test_instrument_tag_rendered_inside():
    fs = Flowsheet("i")
    a = fs.add(U.Instrument("FT-101"))
    b = fs.add(U.Instrument("FIC-101", variant="panel"))
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


def test_tag_splits_type_from_number():
    inst = U.Instrument("FT", 101)
    assert (inst.name, inst.type, inst.number) == ("FT-101", "FT", "101")


def test_combined_tag_still_accepted():
    for tag, expect in (("FT-101", ("FT", "101")), ("PT101A", ("PT", "101A")), ("X", ("X", ""))):
        inst = U.Instrument(tag)
        assert inst.name == tag  # the caller's string is the tag verbatim
        assert (inst.type, inst.number) == expect


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


def test_angle_follows_a_reroute_rather_than_the_screen():
    """A vertical run must put the same tap on its left, not still 'up'."""
    fs = Flowsheet("v")
    feed = fs.add(U.Feed("Feed")).pin(x=60, y=60)
    col = fs.add(U.Column("T-1")).pin(x=300, y=300)
    s = fs.connect(feed.outlet, col.feed)
    inst = fs.add_instrument("PT", 1, on=s, at=0.99, offset=40)
    fs.route()
    pts = [p for p in s.route.waypoints]
    ux, uy = pts[-1][0] - pts[-2][0], pts[-1][1] - pts[-2][1]
    n = math.hypot(ux, uy)
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
    lic = fs.add_instrument("LIC", 101, on=drum, at="E", offset=80, variant="panel")
    fs.route()
    f = drum.frame
    assert lic.tap == pytest.approx((f.x_max, f.cy))
    assert (lic.frame.cx, lic.frame.cy) == pytest.approx((f.x_max + 80, f.cy))


def test_unit_face_default_and_validation():
    fs = Flowsheet("u")
    drum = fs.add(U.Vessel("V-101")).pin(x=200, y=100)
    assert fs.add_instrument("LT", 1, on=drum).at == "E"
    with pytest.raises(ValueError):
        fs.add_instrument("LT", 2, on=drum, at=0.5)
    with pytest.raises(ValueError):
        fs.add_instrument("LT", 3, on=drum, at="up")


def test_stream_host_rejects_a_face():
    fs = Flowsheet("s")
    feed = fs.add(U.Feed("F"))
    prod = fs.add(U.Product("P"))
    s = fs.connect(feed.outlet, prod.inlet)
    with pytest.raises(ValueError):
        fs.add_instrument("FT", 1, on=s, at="E")
    with pytest.raises(ValueError):
        fs.add_instrument("FT", 2, on=s, at=1.4)


# --- layout ------------------------------------------------------------------


def test_attached_balloons_take_no_rank():
    fs = Flowsheet("rank")
    feed = fs.add(U.Feed("Feed"))
    prod = fs.add(U.Product("Product"))
    s = fs.connect(feed.outlet, prod.inlet)
    ft = fs.add_instrument("FT", 101, on=s, offset=60)
    fic = fs.add_instrument("FIC", 101, on=ft, at="N", offset=60)
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


# --- final control element ---------------------------------------------------


def test_controller_output_routes_to_the_valve_actuator():
    from pfd.layout.attach import stream_path
    from pfd.portgeom import port_point

    fs, _, ft, fv = _line(at=0.4, offset=60)
    fic = fs.add_instrument("FIC", 101, on=ft, at="N", offset=120, angle=35, variant="panel")
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
    assert 'stroke-width="1.5"' in fs.to_svg()  # pneumatic slash ticks drawn


def test_every_valve_variant_has_an_actuator_on_its_symbol():
    from pfd.render.symbols import default_registry

    for variant in (
        "default",
        "gate",
        "globe",
        "ball",
        "butterfly",
        "check",
        "control",
        "needle",
        "three_way",
        "relief",
    ):
        sym = default_registry.get("valve", variant)
        assert "actuator" in sym.ports, variant


def test_relief_valve_is_tagged_as_plain_text_beside_the_symbol():
    fs = Flowsheet("psv")
    drum = fs.add(U.Vessel("V-101")).pin(x=200, y=100)
    psv = fs.add(U.Valve("PSV-308", variant="relief")).pin(x=221, y=20)
    flare = fs.add(U.Product("Flare")).pin(x=400, y=0)
    fs.connect(drum.vent, psv.inlet)
    fs.connect(psv.outlet, flare.inlet)
    svg = fs.to_svg()
    assert ">PSV-308<" in svg  # the whole tag, not letters over a number
    assert psv.frame.label_pos in ("left", "right")  # beside the symbol


def test_hanger_is_not_drawn_where_a_signal_already_joins_the_pair():
    fs, _, ft, _ = _line(at=0.5, offset=60)
    fic = fs.add_instrument("FIC", 101, on=ft, at="N", offset=110, angle=35, variant="panel")
    fs.connect(ft.sig_out, fic.sig_in, kind="electric")
    taps = [ln for ln in fs.to_svg().split("\n") if "<line" in ln and 'stroke-width="1"' in ln]
    assert len(taps) == 1  # the transmitter's impulse line, not a second FT-FIC line


def test_interlock_hangs_off_its_controller_on_a_dashed_line():
    fs, _, ft, _ = _line(at=0.5, offset=60)
    fs.add_instrument("I", 1, on=ft, at="S", offset=44, variant="logic")
    taps = [ln for ln in fs.to_svg().split("\n") if "<line" in ln and 'stroke-width="1"' in ln]
    assert any("stroke-dasharray" in ln for ln in taps)  # instrument host -> dashed
    assert any("stroke-dasharray" not in ln for ln in taps)  # process tap -> solid


def test_balloon_signal_ports_reach_every_face():
    """A balloon is a circle: a signal can meet it anywhere, so its connections
    have no face of their own and every one of them offers all four."""
    from pfd.portgeom import port_anchor

    seen = {}
    for face in ("N", "S", "E", "W"):
        fs = Flowsheet("faces")
        inst = fs.add_instrument("LIC", 101, variant="panel")
        inst.pin(x=200, y=250)
        inst.port_face("sig_out", face)
        fs.layout()
        seen[face] = port_anchor(inst, inst.frame, "sig_out")[2]
    assert seen == {"N": "N", "S": "S", "E": "E", "W": "W"}


def test_balloon_free_ports_may_share_a_face_but_equipment_may_not():
    # The exemption is specific to ports with no fixed face; a vessel's nozzles
    # still own theirs, so overlapping options there stay a defect.
    from pfd.render.symbols import default_registry

    balloon = default_registry.get("instrument", "panel")
    assert {"pv", "sig_in", "sig_out"} <= balloon.free_ports
    assert not default_registry.get("vessel", "horizontal").free_ports
