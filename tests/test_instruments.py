"""Instrumentation subsystem: balloons, tags, attachment, signal lines."""

import math

import pytest

from pandid import Flowsheet, units as U


def _line(**kw):
    """A left-to-right process line with a bubble tapping the middle of it.

    The valve is pinned by its centreline rather than by a literal, so the run
    stays the straight horizontal these tests measure along however tall the
    valve symbol is drawn: a pin tuned to one symbol height puts the nozzle off
    the feed's outlet the moment the artwork is rescaled, and the router answers
    with a jog that every "along the line" assertion here then reads through.
    """
    from pandid.portgeom import resolve_size

    fs = Flowsheet("tap")
    feed = fs.add(U.Feed("Feed")).pin(x=60, y=170)
    fv = fs.add(U.Valve("FV-101", variant="control"))
    fv.pin(x=300, y=195 - resolve_size(fv)[1] / 2)  # feed's outlet is at y=195
    prod = fs.add(U.Product("Product")).pin(x=520, y=170)
    s = fs.connect(feed.outlet, fv.inlet)
    fs.connect(fv.outlet, prod.inlet)
    inst = fs.add_instrument("FT", 101, on=s, **kw)
    fs.route()
    return fs, s, inst, fv


def _hatch_marks(svg: str) -> int:
    """Cross-hatch strokes on pneumatic signal lines.

    Counted by element rather than by stroke width: every line on a signal is
    drawn at the one fine weight ISO 15519-2 Annex A.1.02/A.1.03 puts it at, so
    the width no longer tells a hatch from anything else. A stream is a
    ``<path>`` and the hatch is the only ``<line>`` ink inside the stream group.
    """
    body = svg.split('<g id="streams">', 1)[1].split("</g>", 1)[0]
    return body.count("<line ")


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


def test_the_two_trip_squares_are_the_two_isa_symbols_they_claim_to_be():
    """ANSI/ISA-5.1-2009 draws these as two different symbols, and conflating
    them is what the bare square used to do.

    Table 5.1.2 items 3-5 give the generic interlock logic function a *plain
    diamond*; Table 5.1.1 column B gives the safety instrumented system a
    *diamond inscribed in a square*. Both carry the interlock number in the
    lower half of the diamond, so the number is not what tells them apart --
    the square is.
    """
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
    """The name the package shipped keeps working and keeps drawing the same
    artwork, so no sheet already authored moves."""
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
    """A trip square stands for a function, not a device, so the same tag may be
    drawn at each place it acts -- whichever of the two symbols it is drawn as."""
    fs = Flowsheet("i")
    squares = [fs.add_instrument("I", 1, variant=variant) for _ in range(3)]
    assert [s.tag for s in squares] == ["I-1"] * 3
    assert len({s.name for s in squares}) == 3


def test_a_plain_diamond_and_a_diamond_in_a_square_are_not_one_function():
    """They are different ISA-5.1 symbols, so one of each on a tag is two
    different things claiming to be the same -- the clash `add()` exists for."""
    fs = Flowsheet("i")
    fs.add(U.Instrument("I", 1, variant="sis"))
    with pytest.raises(ValueError, match=r"already exists"):
        fs.add(U.Instrument("I", 1, variant="interlock"))


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
    from pandid.layout.attach import stream_path
    from pandid.portgeom import port_point

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
    assert _hatch_marks(fs.to_svg()) >= 2  # pneumatic slash ticks drawn


def test_every_valve_variant_has_an_actuator_on_its_symbol():
    from pandid.render.symbols import default_registry

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


def _valve_variants() -> list[str]:
    """Every registered valve variant. SymbolRegistry has no "list everything"
    API by design, so the private dict is the only enumeration available."""
    from pandid.render.symbols import default_registry

    return sorted(v for kind, v in default_registry._symbols if kind == "valve")


def test_no_valve_variant_draws_its_actuator_inside_the_body():
    """A signal terminates where it meets the valve: it has no nozzle to reach,
    so the drawn end and the routing anchor are one point.

    They part company when the symbol puts the actuator on interior ink, and
    then the renderer draws the line into the body while the router stops it at
    the edge, leaving a signal that ends in the middle of the valve."""
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
    """``mirrored="y"`` stands the symbol on its head, so the stem points down
    and the signal has to arrive from below.

    An actuator parked at the centre of the box is invariant under that mirror,
    which leaves the operator drawn on top of a valve that has been turned
    upside down."""
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


# --- what decides an impulse line from a functional connection ---------------
#
# The style of the line between a balloon and its host is a statement about the
# *line*: solid says a length of tubing with process fluid in it, dashed says a
# measurement or a command. It used to be chosen by the host's class alone --
# solid off a unit, dashed off a balloon -- which answers a different question,
# and drew a trip square hung on a valve as though the valve were piped to it
# while three identical squares elsewhere on the same sheet were dashed.
#
# So the table below is written as a matrix rather than as a list of the cases
# that were wrong: each half of the edge is varied against the other, and the
# expected style is derived from the two rather than from either.


def _tap_styles(fs) -> dict:
    """``{balloon name: "solid" | "dashed"}`` for every tap line on the sheet."""
    import re

    body = fs.to_svg().split('<g id="instrument_taps">', 1)
    if len(body) == 1:
        return {}
    from pandid.render.svg import tap_lines

    lines = re.findall(r"<line [^>]*/>", body[1].split("</g>", 1)[0])
    assert len(lines) == len(tap_lines(fs))
    return {
        u.name: ("dashed" if "stroke-dasharray" in ln else "solid")
        for (u, _, _), ln in zip(tap_lines(fs), lines)
    }


@pytest.mark.parametrize(
    "variant,style",
    [
        # A bare balloon is ISA-5.1's field-mounted device, and a device in the
        # field is the only thing a length of impulse tubing can reach.
        ("default", "solid"),
        # Everything else is a location or function symbol, and says outright that
        # the function is not out on the plant: a bar across the balloon puts it in
        # a panel, a square around it in the shared display, a hexagon in a computer
        # and a diamond in a logic solver. No tubing runs from a drum to any of
        # those, whatever the drum is.
        ("panel", "dashed"),
        ("aux", "dashed"),
        ("shared", "dashed"),
        ("computer", "dashed"),
        ("sis", "dashed"),
        ("logic", "dashed"),
        ("interlock", "dashed"),
    ],
)
def test_link_style_follows_the_balloon_not_only_its_host(variant, style):
    """One host, every balloon: the host cannot be what decides it.

    The vessel is the same piece of plant in all eight, and full of the same
    fluid. What changes is whether there is anything at the other end of the
    line for that fluid to reach.
    """
    fs = Flowsheet("what is on the end of it")
    drum = fs.add(U.Vessel("V-101")).pin(x=200, y=200)
    fs.add_instrument("LX", 101, on=drum, at="E", offset=80, variant=variant)
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
    """One field balloon, every host: the balloon cannot be what decides it
    either. Both ends are asked, and the line is tubing only if both answer."""
    fs = Flowsheet("what it comes off")
    feed = fs.add(U.Feed("Feed")).pin(x=60, y=170)
    drum = fs.add(U.Vessel("V-101")).pin(x=400, y=140)
    line = fs.connect(feed.outlet, drum.inlet)
    hosts = {"stream": lambda: (line, {"at": 0.5}), "vessel": lambda: (drum, {"at": "S"})}
    if host == "valve":
        valve = fs.add(U.Valve("XV-1", variant="solenoid")).pin(x=200, y=300)
        hosts["valve"] = lambda: (valve, {"at": "S"})
    elif host in ("instrument", "signal"):
        lt = fs.add_instrument("LT", 101, on=drum, at="E", offset=70)
        lic = fs.add_instrument("LIC", 101, on=lt, at="E", offset=70, variant="shared")
        signal = fs.connect(lt.sig_out, lic.sig_in, kind="electric")
        hosts["instrument"] = lambda: (lt, {"at": "N"})
        hosts["signal"] = lambda: (signal, {"at": 0.5})
    on, where = hosts[host]()
    fs.add_instrument("PX", 1, on=on, offset=70, variant="default", **where)
    fs.route()
    assert _tap_styles(fs)["PX-1"] == style


def test_the_trip_square_on_a_valve_is_drawn_as_the_signal_it_is():
    """The defect as reported, from ``examples/11_ethanol_pid``.

    Five trip squares on that sheet, one logic function, and the four hung on
    balloons were dashed while the one hung on the feed's solenoid valve was
    solid -- so the sheet drew the same command as tubing in one place and as a
    signal in four. A trip is a signal wherever it acts.
    """
    fs = Flowsheet("one function, five drawings")
    feed = fs.add(U.Feed("Feed")).pin(x=60, y=170)
    xv = fs.add(U.Valve("XV-301", variant="solenoid")).pin(x=250, port="inlet", y=195)
    prod = fs.add(U.Product("Product")).pin(x=520, y=170)
    fs.connect(feed.outlet, xv.inlet)
    fs.connect(xv.outlet, prod.inlet)
    ti = fs.add_instrument("TI", 325, on=xv, at="N", offset=44)
    fs.add_instrument("I", 2, on=xv, at="S", offset=44, variant="sis")
    fs.add_instrument("I", 2, on=ti, at="E", offset=44, variant="sis")
    fs.route()
    styles = _tap_styles(fs)
    assert styles["I-2"] == styles["I-2 (2)"] == "dashed"
    # ...and the gauge reading the same valve is still tubing, so this is not
    # the whole sheet quietly going dashed.
    assert styles["TI-325"] == "solid"


def test_balloon_signal_ports_reach_every_face():
    """A balloon is a circle: a signal can meet it anywhere, so its connections
    have no face of their own and every one of them offers all four."""
    from pandid.portgeom import port_anchor

    seen = {}
    for face in ("N", "S", "E", "W"):
        fs = Flowsheet("faces")
        inst = fs.add_instrument("LIC", 101, variant="panel")
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
    """The panel and aux variants draw a location bar across the middle of the
    circle, right where the tag letters would otherwise sit. ISA-5.1 puts the
    letters wholly above the bar and the number wholly below."""
    import re

    from pandid.render.symbols import default_registry

    for variant, bars in (("panel", (22.0,)), ("aux", (19.0, 25.0))):
        fs = Flowsheet(f"bar-{variant}")
        inst = fs.add_instrument("LIC", 101, variant=variant).pin(x=200, y=200)
        fs.layout()
        svg = fs.to_svg(check=False)
        sym = default_registry.get("instrument", variant)
        # Balloon centre in sheet coordinates, and the bars relative to it.
        cy = inst.frame.y + inst.frame.h / 2
        band = [cy + b - sym.height / 2 for b in bars]

        ys = {
            t: float(y)
            for y, t in re.findall(r'<text x="[\d.]+" y="([\d.]+)"[^>]*>(LIC|101)</text>', svg)
        }
        assert len(ys) == 2, f"{variant}: expected both tag lines, got {ys}"
        # 12pt letters and an 11pt number, centred on their baselines.
        assert ys["LIC"] + 6 <= min(band), f"{variant}: letters run into the bar"
        assert ys["101"] - 5.5 >= max(band), f"{variant}: number runs into the bar"


def test_a_short_pneumatic_run_still_gets_its_cross_hatch():
    """ISA draws a pneumatic signal as a *solid* line marked with double
    cross-hatches, so the hatch is the only thing distinguishing it from process
    piping. One mark per 45px alone leaves a short run (a transducer to the
    actuator right beneath it) with none at all, rendering it as plain pipe."""
    fs = Flowsheet("short-pneumatic")
    valve = fs.add(U.Valve("LV-101", variant="control")).pin(x=300, y=300)
    ly = fs.add_instrument("LY", 101, on=valve, at="N", offset=58)
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
    """One trip acting on *n* valves: the shape of P&ID_301's interlock I 1."""
    fs = Flowsheet("interlock")
    pairs = []
    for i in range(n):
        valve = fs.add(U.Valve(f"XV-{i + 1}", variant="control")).pin(x=200 + 260 * i, y=400)
        square = fs.add(U.Instrument("I", 1, variant="logic")).pin(x=210 + 260 * i, y=250)
        fs.connect(square.sig_out, valve.actuator, kind="electric")
        pairs.append((square, valve))
    return fs, pairs


def test_an_interlock_square_is_drawn_at_every_place_it_acts():
    """P&ID_301 draws interlock I 1 four times: one logic function, tripping
    four valves, shown where each of them is. A sheet that cannot repeat the
    square cannot draw the interlock at all."""
    fs, pairs = _interlocked()
    squares = [square for square, _ in pairs]
    assert [s.tag for s in squares] == ["I-1"] * 4
    assert [s.name for s in squares] == ["I-1", "I-1 (2)", "I-1 (3)", "I-1 (4)"]


def test_each_repeated_square_is_still_one_unit_to_look_up():
    """The tag repeats; the name does not, so a stream endpoint, a spec entry
    and an equipment-list row still each mean exactly one square."""
    fs, pairs = _interlocked()
    for square, valve in pairs:
        assert [u for u in fs.units if u.name == square.name] == [square]
        assert square.sig_out.stream.dest.owner is valve


def test_the_repeated_square_draws_the_tag_it_shares():
    """The name that tells two squares apart is the flowsheet's bookkeeping. The
    square drawn carries the interlock number, four times over."""
    fs, _ = _interlocked()
    svg = fs.to_svg()
    assert svg.count(">1</text>") == 4
    assert "(2)" not in svg


def test_two_transmitters_on_one_loop_number_are_refused():
    """A balloon is a device and there is one of it: a second LT-101 is a tag
    used twice, not one measurement shown twice."""
    fs = Flowsheet("loop")
    fs.add(U.Instrument("LT", 101))
    with pytest.raises(ValueError, match="already exists on this flowsheet"):
        fs.add(U.Instrument("LT", 101))


@pytest.mark.parametrize("variants", [("logic", "default"), ("default", "logic")])
def test_a_square_and_a_balloon_cannot_share_a_tag(variants):
    """Two different symbols claiming to be the same thing, whichever is drawn
    first."""
    first, second = variants
    fs = Flowsheet("mixed")
    fs.add(U.Instrument("I", 1, variant=first))
    with pytest.raises(ValueError, match="already exists on this flowsheet"):
        fs.add(U.Instrument("I", 1, variant=second))


def test_a_repeated_square_survives_a_round_trip_through_a_spec():
    """Each square is written out and read back as its own entry, wired to its
    own valve, which is what needs a name the spec can address it by."""
    fs, _ = _interlocked()
    spec = fs.to_dict()
    rebuilt = Flowsheet.from_dict(spec)
    assert sorted(u.name for u in rebuilt.units) == sorted(u.name for u in fs.units)
    assert [(s.source.owner.name, s.dest.owner.name) for s in rebuilt.streams] == [
        (s.source.owner.name, s.dest.owner.name) for s in fs.streams
    ]
    assert rebuilt.to_dict() == spec


# --- the signal pool: several connections on one balloon ----------------------
#
# P&ID-301 ("Ethanol Purification A300 -- Process & Instrumentation Diagram 1",
# Rev B, 30/10/2025) draws PIC-301 with one signal line in from PT-301 and two
# out, one to CV-301-1 and one to CV-301-2, and letters the split-range bands
# beside them: `0-95%` alongside the leg that drops to CV-301-1, `95-100%` on
# the leg that runs right to CV-301-2. That sheet is in this repository and this
# package could not draw it, because a balloon had exactly one sig_out.


def _split_range():
    """P&ID-301's loop 301: one controller, two control valves, both strokes.

    Pinned rather than laid out, so what the assertions read is the pool and the
    face selection rather than whatever the ranking phase decided this week.
    """
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
    """The sheet the package could not draw. Two outputs off one balloon, each
    landing on its own valve's stem, and the drawing comes out."""
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
    """``sig_out`` is a pool. Asking it to drive a second valve mints a member
    rather than refusing, which is how an author writes split range; and the
    first line stays exactly where it was, so ``pic.sig_out.stream`` still reads
    back the connection it was given."""
    _, _, _, pic, (_, lo), (_, hi) = _split_range()
    assert lo.source is pic.sig_out
    assert pic.sig_out.stream is lo
    assert hi.source.name == "sig_out_2"
    assert list(pic.ports) == ["pv", "sig_in", "sig_out", "sig_out_2"]


def test_a_balloon_with_one_line_each_way_grows_nothing():
    """The pool costs the ordinary case nothing: three ports, the three it has
    always had, in the order it has always had them. Every balloon in
    ``tests/golden`` is one of these, and this is why none of them moved."""
    fs = Flowsheet("plain")
    a = fs.add(U.Instrument("FT-101"))
    b = fs.add(U.Instrument("FIC-101", variant="panel"))
    fs.connect(a.sig_out, b.sig_in, kind="electric")
    assert list(a.ports) == ["pv", "sig_in", "sig_out"]
    assert list(b.ports) == ["pv", "sig_in", "sig_out"]


def test_a_minted_connection_is_drawn_on_the_balloons_own_nozzle():
    """A pool member is not a nozzle the symbol has to be redrawn for. It takes
    the menu its pool's first member has -- all four faces, since a balloon is a
    circle -- so it lands on ink and not on the box-centre fallback."""
    from pandid.portgeom import is_anchored, port_faces

    _, _, _, pic, _, _ = _split_range()
    assert is_anchored(pic, "sig_out_2")
    assert set(port_faces(pic, "sig_out_2")) == set(port_faces(pic, "sig_out"))
    assert set(port_faces(pic, "sig_out_2")) == {"N", "S", "E", "W"}


def test_each_output_takes_a_face_of_its_own():
    """Two live connections may not resolve to one point, and the face selector
    is what keeps that true as the pool grows: it serves each port in turn and
    will not put one on a placement already spoken for."""
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
    """ISO 15519-2 §6.2 (p.14): signal lines for functions inside the PCI symbol
    and for functions outside it "shall be drawn separate between the PCI
    symbols". A high alarm and a low alarm therefore each take a line from the
    measurement rather than being chained one behind the other, which needs two
    outputs on the transmitter."""
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
    """P&ID-301 runs I-2 into LAH-322 and LAL-322 out into I-1. An alarm that
    participates in a trip is a balloon with connections of its own, and it may
    need one of each."""
    fs = Flowsheet("trip")
    lt = fs.add(U.Instrument("LT", 322)).pin(x=120, y=300)
    lal = fs.add(U.Instrument("LAL", 322, variant="shared")).pin(x=360, y=300)
    trip = fs.add(U.Instrument("I", 1, variant="sis")).pin(x=600, y=300)
    fs.connect(lt.sig_out, lal.sig_in, kind="electric")
    fs.connect(lal.sig_out, trip.sig_in, kind="electric")
    assert lal.sig_in.stream.source.owner is lt
    assert lal.sig_out.stream.dest.owner is trip


def test_a_signal_connection_takes_either_end_of_its_line():
    """A signal port carries no direction requirement. The same terminal is fed
    on one sheet and trips from it on another, so which end it took is read off
    the stream and not declared in advance."""
    fs = Flowsheet("either end")
    a = fs.add(U.Instrument("LAL-322", variant="shared"))
    b = fs.add(U.Instrument("I-1", variant="sis"))
    # ``sig_in`` as the source: named for the author's reading, not enforced.
    s = fs.connect(a.sig_in, b.sig_in, kind="electric")
    assert s.source is a.sig_in and s.dest is b.sig_in
    assert s.source.direction == "inlet"  # the field is a label, not a rule


def test_a_process_nozzle_still_has_a_direction():
    """The guard is not gone, it is narrowed. Fluid enters a nozzle or leaves
    it, and a pipe drawn the other way is still refused."""
    fs = Flowsheet("piping")
    p1 = fs.add(U.Pump("P-101"))
    p2 = fs.add(U.Pump("P-102"))
    with pytest.raises(ValueError, match="must be an outlet"):
        fs.connect(p1.suction, p2.discharge)
    with pytest.raises(ValueError, match="must be an inlet"):
        fs.connect(p1.discharge, p2.discharge)


def test_the_process_tap_is_one_tap():
    """``pv`` is not a pool. An instrument taps one process point, and a second
    line to it is a mistake in the drawing rather than a request for another
    connection. (A differential instrument tapping two points wants a second
    *named* tap, high and low; nothing here is designed for it.)"""
    fs = Flowsheet("tap")
    fic = fs.add(U.Instrument("FIC-301", variant="shared"))
    a = fs.add(U.Instrument("FT-301"))
    b = fs.add(U.Instrument("FT-302"))
    fs.connect(a.sig_out, fic.pv, kind="electric")
    with pytest.raises(ValueError, match=r"FIC-301\.pv is already connected"):
        fs.connect(b.sig_out, fic.pv, kind="electric")


def test_a_valve_has_one_actuator():
    """Split range is one actuator per valve with the controller holding two
    outputs, so the stem stays singular and a second line onto it is refused."""
    fs = Flowsheet("stem")
    cv = fs.add(U.Valve("CV-301-1", variant="control"))
    a = fs.add(U.Instrument("PIC-301", variant="shared"))
    b = fs.add(U.Instrument("HIC-301", variant="shared"))
    fs.connect(a.sig_out, cv.actuator, kind="pneumatic")
    with pytest.raises(ValueError, match=r"CV-301-1\.actuator is already connected"):
        fs.connect(b.sig_out, cv.actuator, kind="pneumatic")


# --- naming the units instead of their connections ----------------------------


def test_naming_the_units_draws_the_signal_line():
    """On a signal line the connection is not information: a balloon mints one
    per line and a control valve has exactly one stem. So either end may be the
    unit and the engine picks."""
    fs = Flowsheet("units")
    ft = fs.add(U.Instrument("FT-305"))
    fic = fs.add(U.Instrument("FIC-305", variant="shared"))
    cv = fs.add(U.Valve("CV-305", variant="control"))
    a = fs.connect(ft, fic, kind="electric")
    b = fs.connect(fic, cv, kind="pneumatic")
    assert (a.source.name, a.dest.name) == ("sig_out", "sig_in")
    assert (b.source.name, b.dest.name) == ("sig_out", "actuator")


def test_naming_the_units_mints_a_second_output():
    """The split-range case written the short way."""
    fs = Flowsheet("units split")
    pic = fs.add(U.Instrument("PIC-301", variant="shared"))
    cv1 = fs.add(U.Valve("CV-301-1", variant="control"))
    cv2 = fs.add(U.Valve("CV-301-2", variant="control"))
    fs.connect(pic, cv1, kind="pneumatic")
    fs.connect(pic, cv2, kind="pneumatic")
    assert list(pic.ports) == ["pv", "sig_in", "sig_out", "sig_out_2"]


def test_piping_still_names_its_nozzle():
    """Which nozzle a pipe runs to is the whole question -- a column has a feed,
    an overhead and a bottoms -- so a process kind refuses a bare unit."""
    fs = Flowsheet("piping")
    p1 = fs.add(U.Pump("P-101"))
    p2 = fs.add(U.Pump("P-102"))
    with pytest.raises(ValueError, match="a unit rather than one of its nozzles"):
        fs.connect(p1, p2)


def test_a_unit_with_no_signal_connection_is_named_not_guessed_at():
    """A pump has no stem for a signal line to reach, so naming it refuses and
    says which nozzles it does have."""
    fs = Flowsheet("no stem")
    pic = fs.add(U.Instrument("PIC-301", variant="shared"))
    pump = fs.add(U.Pump("P-101"))
    with pytest.raises(ValueError, match="has no signal connection"):
        fs.connect(pic, pump, kind="electric")


def test_a_unit_with_several_signal_connections_is_not_guessed_at():
    """Two signal connections that are not a pool are two different things, so
    this refuses rather than picking one."""
    fs = Flowsheet("ambiguous")
    pic = fs.add(U.Instrument("PIC-301", variant="shared"))
    station = fs.add(U.Valve("CV-301", variant="control"))
    station._add_port("sig_spare", "inlet", "signal")
    with pytest.raises(ValueError, match="2 signal connections"):
        fs.connect(pic, station, kind="pneumatic")


def test_split_range_survives_a_round_trip_through_a_spec():
    """A minted connection is written out under its own name and read back by
    it, so a sheet the pool was used on rebuilds exactly."""
    fs, *_ = _split_range()
    spec = fs.to_dict()
    rebuilt = Flowsheet.from_dict(spec)
    pic = next(u for u in rebuilt.units if u.name == "PIC-301")
    assert list(pic.ports) == ["pv", "sig_in", "sig_out", "sig_out_2"]
    assert rebuilt.to_dict() == spec


def test_a_refused_connection_mints_nothing():
    """Both refusals are made before either end is taken, so a call that raises
    leaves the sheet exactly as it found it. A balloon carrying a spare nozzle
    no line reaches is a drawing changed by an error, and ``debug=True`` draws
    every port it has."""
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


def test_a_fifth_line_onto_a_balloon_is_reported_not_hidden():
    """A balloon is a circle with four faces, so the fifth connection has
    nowhere of its own to go and lands on a placement already taken. The pool
    does not pretend otherwise: the face selector leaves it on the symbol's own
    nozzle and ``validate`` reports the stack as a hard error, which is the
    signal to draw a trunk with stubs instead."""
    from pandid.validate import validate

    fs = Flowsheet("crowded")
    pic = fs.add(U.Instrument("PIC-301", variant="shared")).pin(x=400, y=400)
    for i in range(5):
        cv = fs.add(U.Valve(f"CV-{i}", variant="control")).pin(x=100 + 180 * i, y=700)
        fs.connect(pic.sig_out, cv.actuator, kind="pneumatic")
    fs.route()
    assert [i.code for i in validate(fs) if i.severity == "error"] == ["coincident-ports"]


def test_a_pool_member_can_be_asked_for_by_name():
    """``signal_port`` is how a member the balloon has not grown yet is reached
    -- what the spec reader needs, and what an author needs to name a face on
    one before the line that mints it is written."""
    fs = Flowsheet("by name")
    pic = fs.add(U.Instrument("PIC-301", variant="shared"))
    port = pic.signal_port("sig_out_2")
    assert port.name == "sig_out_2" and port.role == "signal"
    assert pic.signal_port("sig_out_2") is port  # asked twice, minted once
    assert pic.signal_port("sig_out") is pic.sig_out
    with pytest.raises(KeyError, match="signal pools"):
        pic.signal_port("sig_sideways")
