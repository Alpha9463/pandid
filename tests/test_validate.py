"""Validation: hard errors raise from render(); soft issues warn."""

import ast
import re
from dataclasses import replace
from typing import Any, cast

import pytest

from pandid import Condenser, Flowsheet, Pin, Stream, units as U
from pandid.portgeom import pin_intent, pinned_x, pinned_y, port_point, resolve_port
from pandid.render.symbols import default_registry
from pandid.validate import OFFSET_BY_DESIGN
from test_symbol_invariants import _drawing


def _found(fs: Flowsheet, code: str, **kw: Any) -> list:
    """Return the findings of one code."""
    return [i for i in fs.validate(**kw) if i.code == code]


def _overlapping_reactors() -> Flowsheet:
    """Build two reactors pinned on top of each other."""
    fs = Flowsheet("overlap")
    a = fs.add(U.Reactor("R1")).pin(x=100, y=100)
    b = fs.add(U.Reactor("R2")).pin(x=110, y=110)
    fs.connect(a.outlet, b.feed)
    return fs


def test_overlapping_pins_raise():
    fs = _overlapping_reactors()
    with pytest.raises(ValueError, match="overlap"):
        fs.to_svg()


# --- unit-overlap says how to clear it ----------------------------------------


def _overlap_message(fs: Flowsheet) -> str:
    said = [i.message for i in fs.validate() if i.code == "unit-overlap"]
    assert len(said) == 1, said
    return said[0]


def _tapped_line() -> tuple[Flowsheet, U.Valve, U.Instrument]:
    """Build a valve on a line with a transmitter attached to the line before it."""
    fs = Flowsheet("tapped")
    feed = fs.add(U.Feed("F"))
    fv = fs.add(U.Valve("FV-101"))
    prod = fs.add(U.Product("P"))
    s = fs.connect(feed.outlet, fv.inlet)
    fs.connect(fv.outlet, prod.inlet)
    ft = fs.add_instrument("FT", 101, sensing=s)
    fs.route()
    return fs, fv, ft


def test_unit_overlap_moves_an_attached_balloon_with_at_and_offset():
    """Verify the overlap message tells an attached balloon to move by at= and offset=."""
    fs, fv, ft = _tapped_line()
    assert fv.frame is not None and ft.frame is not None
    ft.frame = replace(ft.frame, x=fv.frame.x, y=fv.frame.y)

    said = _overlap_message(fs)
    assert said.startswith("FV-101 and FT-101 overlap. FT-101 hangs off S1")
    assert "at=" in said and "offset=" in said
    assert "call .attach(<the S1 stream>, at=..., offset=...) on FT-101" in said
    assert "pin(" not in said


def test_unit_overlap_moves_a_pinned_balloon_by_its_pin():
    """Check that the overlap message tells a pinned balloon to move by its pin."""
    fs, fv, ft = _tapped_line()
    # A line too short for the valve to step clear of the balloon.
    feed, _, prod = fs.units[:3]
    feed.pin(port="outlet", x=100, y=100)
    prod.pin(port="inlet", x=200, y=100)
    fs.route()
    assert fv.frame is not None
    ft.pin(x=fv.frame.x, y=fv.frame.y)
    fs.route()

    said = _overlap_message(fs)
    assert "FT-101 is pinned there" in said
    assert "call .pin(x=..., y=...) on FT-101" in said
    assert "offset=" not in said


def test_unit_overlap_moves_one_of_two_pinned_units_by_its_pin():
    fs = _overlapping_reactors()
    fs.route()

    said = _overlap_message(fs)
    assert said.startswith("R1 and R2 overlap. Both are pinned")
    assert "call .pin(x=..., y=...) on R2" in said


def test_unit_overlap_repins_by_the_port_a_unit_is_pinned_by():
    """Check that the suggested pin() call repeats the port each axis is pinned by."""
    fs = Flowsheet("overlap")
    a = fs.add(U.Valve("V-1")).pin(x=100, y=100)
    b = fs.add(U.Valve("V-2")).pin(port="inlet", x=105, y=100)
    c = fs.add(U.Valve("V-3")).pin(port="inlet", x=300).pin(port="outlet", y=100)
    fs.connect(a.outlet, b.inlet)
    fs.route()

    said = _overlap_message(fs)
    call = re.search(r"call \.pin\((.*?)\) on V-2", said)
    assert call is not None, said
    kwargs: dict[str, Any] = {}
    for arg in call.group(1).split(", "):
        key, value = arg.split("=", 1)
        kwargs[key] = 150.0 if value == "..." else ast.literal_eval(value)
    b.pin(**kwargs)
    assert b._pin_ports == {"x": "inlet", "y": "inlet"}

    # Axes pinned by different ports get a call each.
    from pandid.validate import _overlap_cure

    cure = _overlap_cure(a, c)
    assert (
        "call .pin(port='inlet', x=...) on V-3 and call .pin(port='outlet', y=...) on V-3"
    ) in cure


def test_unit_overlap_pins_one_of_two_units_the_layout_placed():
    """Check that two units the layout placed are told to pin one of them."""
    fs, fv, _ = _tapped_line()
    pump = fs.add(U.Pump("P-101"))
    fs.route()
    assert fv.frame is not None and pump.frame is not None
    pump.frame = replace(pump.frame, x=fv.frame.x, y=fv.frame.y)

    said = _overlap_message(fs)
    assert "the layout placed both there" in said
    assert "call .pin(x=..., y=...) on P-101" in said


def test_unit_overlap_suggests_an_attach_that_keeps_what_the_balloon_does():
    """Check that the suggested attach() call keeps the balloon's relation and angle."""
    fs, fv, _ = _tapped_line()
    fic = fs.add_instrument("FIC", 101, near=fv, angle=45.1234567)
    fs.route()
    assert fv.frame is not None and fic.frame is not None
    fic.frame = replace(fic.frame, x=fv.frame.x, y=fv.frame.y)

    said = _overlap_message(fs)
    call = re.search(r"call \.attach\(<the FV-101 unit>, (.*?)\) on FIC-101", said)
    assert call is not None, said
    filled: dict[str, Any] = {"face": "N", "offset": 70.0}
    kwargs: dict[str, Any] = {}
    for arg in call.group(1).split(", "):
        key, value = arg.split("=", 1)
        kwargs[key] = filled[key] if value == "..." else ast.literal_eval(value)
    fic.attach(fv, **kwargs)
    assert (fic.relation, fic.angle, fic.face, fic.offset) == ("near", 45.1234567, "N", 70.0)


def test_unit_overlap_does_not_offer_a_grid_pin_to_an_attached_balloon():
    """Check that an attached balloon is offered attach() and an x/y pin, not col=."""
    fs, fv, ft = _tapped_line()
    ft.pin(col=1, row=1)
    fs.route()
    assert fv.frame is not None and ft.frame is not None
    ft.frame = replace(ft.frame, x=fv.frame.x, y=fv.frame.y)

    said = _overlap_message(fs)
    assert "call .attach(<the S1 stream>, at=..., offset=...) on FT-101" in said
    assert "call .pin(x=..., y=...) on FT-101" in said
    assert "col=..." not in said


@pytest.mark.parametrize(
    ("pinned", "call"),
    [
        ({"col": 2}, "call .pin(col=...) on P-101"),
        ({"row": 1}, "call .pin(row=...) on P-101"),
        ({"x": 400}, "call .pin(x=...) on P-101"),
        ({"y": 300}, "call .pin(y=...) on P-101"),
        ({"col": 2, "y": 300}, "call .pin(col=..., y=...) on P-101"),
        ({"col": 2, "row": 1}, "call .pin(col=..., row=...) on P-101"),
        ({"x": 400, "y": 300}, "call .pin(x=..., y=...) on P-101"),
        ({}, "call .pin(x=..., y=...) on P-101"),
    ],
    ids=["col", "row", "x", "y", "col-y", "col-row", "x-y", "none"],
)
def test_unit_overlap_repins_only_the_axes_a_unit_pins(pinned: dict[str, Any], call: str):
    """Check that the suggested pin() names only the axes already pinned."""
    fs, fv, _ = _tapped_line()
    pump = fs.add(U.Pump("P-101"))
    if pinned:
        pump.pin(**pinned)
    fs.route()
    assert fv.frame is not None and pump.frame is not None
    pump.frame = replace(pump.frame, x=fv.frame.x, y=fv.frame.y)

    said = _overlap_message(fs)
    assert said.endswith(f": {call}"), said


def _balloon_on_valve(axis: str) -> tuple[Flowsheet, U.Valve, U.Instrument]:
    """Build a transmitter pinned on one axis where the layout draws it on the valve."""
    fs, fv, ft = _tapped_line()
    assert fv.frame is not None and ft.host is not None
    if axis == "x":
        ft.attach(ft.host, offset=5).pin(x=fv.frame.x)
    else:
        ft.attach(ft.host, at=1.0).pin(y=fv.frame.y)
    fs.route()
    return fs, fv, ft


@pytest.mark.parametrize("axis", ["x", "y"])
def test_unit_overlap_repins_a_balloon_only_on_its_pinned_axis(axis: str):
    """Check that a balloon pinned on one axis is told to move that axis alone."""
    fs, _, _ = _balloon_on_valve(axis)

    said = _overlap_message(fs)
    assert said.endswith(
        f"FT-101 is pinned there, so move its pin clear of FV-101: call .pin({axis}=...) on FT-101"
    ), said


@pytest.mark.parametrize(
    ("pinned", "advice"),
    [
        (
            {"col": 1},
            "Its col= pin does not move an attached balloon; an x= pin does: "
            "call .pin(x=...) on FT-101",
        ),
        (
            {"row": 1},
            "Its row= pin does not move an attached balloon; a y= pin does: "
            "call .pin(y=...) on FT-101",
        ),
    ],
    ids=["col", "row"],
)
def test_unit_overlap_offers_a_balloon_the_axis_its_grid_pin_names(
    pinned: dict[str, Any], advice: str
):
    """Check that a balloon pinned by col= or row= alone is offered that axis alone."""
    fs, fv, ft = _tapped_line()
    ft.pin(**pinned)
    fs.route()
    assert fv.frame is not None and ft.frame is not None
    ft.frame = replace(ft.frame, x=fv.frame.x, y=fv.frame.y)

    said = _overlap_message(fs)
    assert said.endswith(f". {advice}"), said


def test_following_the_overlap_advice_clears_it_and_leaves_free_axes_free():
    """Check that the suggested pin(), given a value, clears the overlap alone."""
    fs, fv, ft = _balloon_on_valve("x")
    assert fv.frame is not None
    clear = fv.frame.x - 100
    call = re.search(r"call \.pin\((.*?)\) on FT-101", _overlap_message(fs))
    assert call is not None
    kwargs: dict[str, Any] = {}
    for arg in call.group(1).split(", "):
        key, value = arg.split("=", 1)
        assert value == "...", arg
        kwargs[key] = clear
    ft.pin(**kwargs)
    fs.route()

    assert _found(fs, "unit-overlap") == []
    assert pin_intent(ft) == {"x": (None, clear)}


def test_negative_pin_raises():
    fs = Flowsheet("oob")
    a = fs.add(U.Feed("F")).pin(x=-50, y=10)
    b = fs.add(U.Product("P")).pin(x=200, y=10)
    fs.connect(a.outlet, b.inlet)
    with pytest.raises(ValueError, match="negative|off-sheet"):
        fs.to_svg()


def test_check_false_bypasses_validation():
    svg = _overlapping_reactors().to_svg(check=False)  # must not raise
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
    """Build a valve loop with a transmitter and a controller balloon on signals."""
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


def test_two_lines_named_onto_one_face_of_a_balloon_are_drawn_apart():
    """Check that two lines put on one face of a balloon keep it at two points."""
    fs, lic = _loop_with_a_balloon()
    lic.nozzle("sig_in", "W")
    lic.nozzle("sig_out", "W")
    fs.layout()
    assert lic.frame is not None
    ends = [resolve_port(lic, lic.frame, name) for name in ("sig_in", "sig_out")]
    assert [end.face for end in ends] == ["W", "W"]
    assert ends[0].point != ends[1].point
    assert [i for i in fs.validate() if i.severity == "error"] == []


def test_distinct_placements_on_the_same_balloon_are_fine():
    fs, lic = _loop_with_a_balloon()
    lic.nozzle("sig_out", "N")
    fs.layout()
    assert _found(fs, "coincident-ports") == []


def test_ports_the_symbol_never_anchored_warn_rather_than_raise(gapped_kind):
    """Check that ports a symbol does not anchor coincide as a warning, not an error."""
    fs = Flowsheet("gapped")
    unit = fs.add(gapped_kind("G-1"))
    prod = fs.add(U.Product("P"))
    for port in ("inlet", "spare_a", "spare_b"):
        feed = fs.add(U.Feed(f"F-{port}"))
        fs.connect(feed.outlet, unit.ports[port])
    fs.connect(unit.outlet, prod.inlet)
    fs.layout()
    issues = _found(fs, "coincident-ports")
    assert [i.severity for i in issues] == ["warning"]
    assert "anchors no nozzle" in issues[0].message
    fs.to_svg()  # must not raise


# --- a nozzle drawn off the body it belongs to --------------------------------


class _StubbedTank(U.Unit):
    kind = "off_body_test_unit"
    PORTS = [("inlet", "inlet", "process"), ("outlet", "outlet", "process")]


@pytest.fixture
def off_body_kind():
    """Register a symbol whose outlet is drawn 30 units below its own box."""
    from pandid.render.symbols import Symbol

    default_registry.register(
        _StubbedTank.kind,
        Symbol(
            svg='<g id="sym_off_body_test"><rect x="0" y="0" width="60" height="60" '
            'fill="none" stroke="black" stroke-width="2"/></g>',
            width=60.0,
            height=60.0,
            ports={"inlet": (0.0, 30.0), "outlet": (30.0, 90.0)},
        ),
    )
    try:
        yield _StubbedTank
    finally:
        del default_registry._symbols[(_StubbedTank.kind, "default")]


def _sheet_with(kind):
    fs = Flowsheet("off-body")
    unit = fs.add(kind("X-1"))
    fs.connect(fs.add(U.Feed("F")).outlet, unit.ports["inlet"])
    fs.connect(unit.ports["outlet"], fs.add(U.Product("P")).inlet)
    return fs


def test_a_nozzle_drawn_off_its_own_body_is_reported(off_body_kind):
    """Check that a nozzle outside its unit's box is a nozzle-off-body error."""
    fs = _sheet_with(off_body_kind)
    fs.layout()
    issues = _found(fs, "nozzle-off-body")
    assert [i.severity for i in issues] == ["error"]
    assert "X-1.outlet" in issues[0].message
    assert "outside X-1's own box" in issues[0].message
    with pytest.raises(ValueError, match="nozzle-off-body"):
        fs.to_svg()


def test_a_nozzle_on_the_edge_of_its_body_is_not_off_it(off_body_kind):
    """Check that a nozzle on the edge of its box is not reported off it."""
    fs = _sheet_with(off_body_kind)
    fs.layout()
    issues = _found(fs, "nozzle-off-body")
    assert [i for i in issues if "X-1.inlet" in i.message] == []


def test_the_shipped_corpus_draws_no_nozzle_off_a_body():
    """Check that a tank fed three ways reports no nozzle off its body."""
    fs = Flowsheet("three-fills")
    tank = U.Tank("TK-1", inputs=3)
    fs.add(tank)
    for i in (1, 2, 3):
        fs.connect(fs.add(U.Feed(f"F-{i}")).outlet, tank.ports[f"in_{i}"])
    fs.connect(tank.outlet, fs.add(U.Product("P")).inlet)
    fs.layout()
    assert _found(fs, "nozzle-off-body") == []


def test_an_extractive_towers_feeds_get_nozzles_of_their_own():
    """Check that a two-feed column gives each feed a nozzle of its own."""
    fs = Flowsheet("extractive")
    col = fs.add(U.Column("T-302", n_feeds=2))
    for port in ("feed_1", "feed_2"):
        feed = fs.add(U.Feed(port))
        fs.connect(feed.outlet, col.ports[port])
    fs.connect(col.overhead, fs.add(U.Product("D")).inlet)
    fs.connect(col.bottoms, fs.add(U.Product("B")).inlet)
    fs.layout()
    assert _found(fs, "coincident-ports") == []
    fs.to_svg()  # must not raise


def test_two_feeds_pinned_to_the_same_stage_are_coincident():
    """Check that two feeds on the same stage are reported as coincident ports."""
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
    """Check that a kettle reboiler's bottoms draw is a nozzle of its own."""
    fs = Flowsheet("reboiler")
    col = fs.add(U.DistillationColumn("T-701"))
    reb = fs.add(U.HeatExchanger("E-702", variant="kettle"))
    fs.connect(col.bottoms, reb.shell_in)
    fs.connect(reb.shell_out, col.boilup_in, draw_as_recycle=True)
    fs.connect(reb.bottoms, fs.add(U.Product("Bottoms")).inlet)
    fs.layout()
    assert _found(fs, "coincident-ports") == []
    fs.to_svg()  # must not raise


def test_a_mixers_extra_inlets_get_nozzles_of_their_own():
    """Check that a four-inlet mixer gives each inlet a nozzle of its own."""
    fs = Flowsheet("wide-mixer")
    mix = fs.add(U.Mixer("M-1", n_inlets=4))
    prod = fs.add(U.Product("P"))
    for i in range(1, 5):
        feed = fs.add(U.Feed(f"F{i}"))
        fs.connect(feed.outlet, mix.ports[f"in_{i}"])
    fs.connect(mix.outlet, prod.inlet)
    fs.layout()
    assert _found(fs, "coincident-ports") == []


# --- near-miss run elevations -------------------------------------------------


def _corner_pinned_run(fv_y=180.0):
    """Build a control valve and a drum corner-pinned onto different elevations."""
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
    issues = _found(fs, "run-off-elevation")
    assert [i.severity for i in issues] == ["warning", "warning"]
    assert "2.6px apart" in issues[0].message
    assert "FV-101.pin(port='inlet', y=195)" in issues[0].message


def test_pinning_the_nozzle_is_the_cure_the_message_names():
    """Check that pinning the nozzle as the message suggests silences the finding."""
    fs, fv = _corner_pinned_run()
    fv.pin(x=270, port="inlet", y=195)
    fs.layout()
    assert _found(fs, "run-off-elevation") == []


def test_a_deliberate_elevation_change_is_not_a_near_miss():
    """Check that two vessels 300px apart in elevation are not reported."""
    fs = Flowsheet("two-levels")
    upper = fs.add(U.Vessel("V-1")).pin(x=100, y=100)
    lower = fs.add(U.Vessel("V-2")).pin(x=400, y=400)
    fs.connect(upper.outlet, lower.inlet)
    fs.layout()
    assert _found(fs, "run-off-elevation") == []


def test_an_eccentric_reducer_is_meant_to_change_centreline():
    """Check that an eccentric reducer's centreline step is not reported."""
    fs = Flowsheet("eccentric")
    feed = fs.add(U.Feed("F")).pin(x=60, port="outlet", y=300)
    red = fs.add(U.Reducer("R-1", variant="eccentric")).pin(x=300, port="inlet", y=300)
    prod = fs.add(U.Product("P")).pin(x=600, port="inlet", y=300)
    fs.connect(feed.outlet, red.inlet)
    fs.connect(red.outlet, prod.inlet)
    fs.layout()
    assert _found(fs, "run-off-elevation") == []


def test_a_concentric_reducer_in_the_same_run_is_not_exempt():
    """Check that a concentric or default reducer is not in OFFSET_BY_DESIGN."""
    assert ("reducer", "concentric") not in OFFSET_BY_DESIGN
    assert ("reducer", "default") not in OFFSET_BY_DESIGN


@pytest.mark.parametrize("variant", ["angle", "psv", "relief"])
def test_a_relief_valve_needs_no_entry_in_the_exemption_set(variant):
    """Check that each relief valve variant keeps a horizontal nozzle pair level."""
    from pandid.geometry import Pin
    from pandid.portgeom import port_faces, port_offset

    assert ("valve", variant) not in OFFSET_BY_DESIGN
    valve = U.Valve("HV-1", variant=variant)
    for turn in (0, 90, 180, 270):
        placed = Pin(x=0.0, y=0.0, orientation=turn)
        faces = {n: port_faces(valve, n, placed)[0] for n in ("inlet", "outlet")}
        if not set(faces.values()) <= {"E", "W"}:
            continue  # a quarter-turn device
        ys = [port_offset(valve, n, placed)[1] for n in ("inlet", "outlet")]
        assert ys[0] == pytest.approx(ys[1]), (variant, turn, faces, ys)


def test_the_eccentric_reducer_is_the_one_that_fails_that_test():
    """Check that an eccentric reducer's run nozzles differ in elevation and are exempt."""
    from pandid.geometry import Pin
    from pandid.portgeom import port_faces, port_offset

    red = U.Reducer("R-1", variant="eccentric")
    placed = Pin(x=0.0, y=0.0)
    assert {port_faces(red, n, placed)[0] for n in ("inlet", "outlet")} == {"E", "W"}
    ys = [port_offset(red, n, placed)[1] for n in ("inlet", "outlet")]
    assert ys[0] != pytest.approx(ys[1])
    assert ("reducer", "eccentric") in OFFSET_BY_DESIGN


def test_an_unpinned_sheet_keeps_its_elevations_to_itself():
    """Check that a sheet with no pins reports no run-off-elevation."""
    fs = Flowsheet("auto")
    feed = fs.add(U.Feed("F"))
    fv = fs.add(U.Valve("FV-1", variant="control"))
    drum = fs.add(U.Vessel("V-1"))
    fs.connect(feed.outlet, fv.inlet)
    fs.connect(fv.outlet, drum.inlet)
    fs.layout()
    assert _found(fs, "run-off-elevation") == []


def test_a_signal_line_has_no_elevation_to_be_off():
    """Check that a signal line to a valve actuator is not reported off elevation."""
    fs = Flowsheet("signal")
    fv = fs.add(U.Valve("FV-1", variant="control")).pin(x=270, y=180)
    drum = fs.add(U.Vessel("V-1")).pin(x=420, y=145)
    prod = fs.add(U.Product("P")).pin(x=700, port="inlet", y=195)
    fs.connect(fv.outlet, drum.inlet)
    fs.connect(drum.outlet, prod.inlet)
    lic = fs.add_instrument("LIC", 101, sensing=drum, face="S", offset=90, display="central")
    fs.connect(lic.sig_out, fv.actuator, kind="electric")
    fs.layout()
    assert [i.message for i in _found(fs, "run-off-elevation") if "LIC" in i.message] == []


def test_a_vertical_drop_is_a_runs_length_and_not_a_miss():
    """Check that a vertical drop between two tanks is not reported off elevation."""
    fs = Flowsheet("drop")
    upper = fs.add(U.Tank("TK-1")).pin(x=200, y=100)
    lower = fs.add(U.Tank("TK-2")).pin(x=205, y=500)
    fs.connect(upper.outlet, lower.inlet)
    fs.layout()
    assert _found(fs, "run-off-elevation") == []


# --- a counted nozzle with no line on it --------------------------------------


def _mixer(n_inlets, wired):
    """Build a mixer for *n_inlets* with only the *wired* inlets piped."""
    fs = Flowsheet("unpiped")
    mix = fs.add(U.Mixer("M-101", n_inlets=n_inlets))
    for i in wired:
        fs.connect(fs.add(U.Feed(f"F-{i}")).outlet, mix.ports[f"in_{i}"])
    fs.connect(mix.outlet, fs.add(U.Product("P")).inlet)
    return fs, mix


@pytest.mark.parametrize(("n_inlets", "wired"), [(4, (1, 2, 3, 4)), (3, (1, 2, 3))])
def test_either_cure_the_message_names_silences_it(n_inlets, wired):
    """Check that wiring the nozzle, or building for the count used, leaves no finding."""
    assert _found(_mixer(n_inlets, wired)[0], "nozzle-unconnected") == []


def test_it_is_reported_before_layout_has_run():
    """Check that nozzle-unconnected is reported before and after layout."""
    fs, mix = _mixer(4, (2, 3, 4))
    assert all(u.frame is None for u in fs.units)
    assert len(_found(fs, "nozzle-unconnected")) == 1
    fs.layout()
    assert len(_found(fs, "nozzle-unconnected")) == 1


@pytest.mark.parametrize(
    ("n_inlets", "wired", "said"),
    [
        # Wired off by one: in_1 is the one left unpiped, with both cures.
        (
            4,
            (2, 3, 4),
            [
                "M-101.in_1 carries no stream",
                "built with 4 numbered nozzles, in_1..in_4, and 3 of them are piped",
                "asserts 4 connections and draws 3",
                "Connect it, or build M-101 with the 3 it uses.",
            ],
        ),
        (
            4,
            (2, 3),
            [
                "M-101.in_1 and M-101.in_4 carry no stream",
                "Connect them, or build M-101 with the 2 it uses.",
            ],
        ),
        (
            2,
            (),
            ["0 of them are piped", "Connect them: nothing is piped to M-101 at all."],
        ),
        (1, (), ["built with 1 numbered nozzle, in_1"]),
    ],
)
def test_a_mixer_short_of_its_count_is_one_finding(n_inlets, wired, said):
    """Check that a mixer's unpiped nozzles make one finding with the right sentence."""
    fs, _ = _mixer(n_inlets, wired)
    issues = _found(fs, "nozzle-unconnected")
    assert [i.severity for i in issues] == ["warning"]
    for text in said:
        assert text in issues[0].message


def test_a_splitter_counts_its_outlets_the_same_way():
    fs = Flowsheet("split")
    sp = fs.add(U.Splitter("SP-1", n_outlets=3))
    fs.connect(fs.add(U.Feed("F")).outlet, sp.inlet)
    for i in (1, 2):
        fs.connect(sp.ports[f"out_{i}"], fs.add(U.Product(f"P{i}")).inlet)
    issues = _found(fs, "nozzle-unconnected")
    assert len(issues) == 1
    assert "SP-1.out_3 carries no stream" in issues[0].message


def test_a_block_is_caught_though_its_symbol_has_no_series():
    """Check that a block's unpiped nozzles are reported, one finding per family."""
    from pandid.render.symbols import default_registry

    fs = Flowsheet("bfd")
    blk = fs.add(U.Block("Reaction", inputs=["W", "W", "N"], outputs=2))
    fs.connect(fs.add(U.Feed("F")).outlet, blk.in_1)
    fs.connect(blk.out_1, fs.add(U.Product("P")).inlet)
    assert default_registry.for_unit(blk).port_series == ()
    issues = _found(fs, "nozzle-unconnected")
    assert len(issues) == 2
    assert "Reaction.in_2 and Reaction.in_3 carry no stream" in issues[0].message
    assert "Reaction.out_2 carries no stream" in issues[1].message


@pytest.mark.parametrize("cls", [U.Vessel, U.Tank], ids=["Vessel", "Tank"])
def test_a_vessels_spare_relief_and_drain_are_not_reported(cls):
    """Check that an unpiped vent, relief and drain on a vessel or tank are not reported."""
    fs = Flowsheet("holdup")
    u = fs.add(cls("V-1"))
    fs.connect(fs.add(U.Feed("F")).outlet, u.inlet)
    fs.connect(u.outlet, fs.add(U.Product("P")).inlet)
    assert _found(fs, "nozzle-unconnected") == []
    assert [n for n in u.ports if u.ports[n].stream is None] == ["vent", "relief", "drain"]


def test_a_column_counts_its_feeds():
    fs = Flowsheet("col")
    col = fs.add(U.Column("T-1", n_feeds=3))
    fs.connect(fs.add(U.Feed("F")).outlet, col.feeds[0])
    fs.connect(col.overhead, fs.add(U.Product("D")).inlet)
    fs.connect(col.bottoms, fs.add(U.Product("B")).inlet)
    issues = _found(fs, "nozzle-unconnected")
    assert len(issues) == 1
    assert "T-1.feed_2 and T-1.feed_3 carry no stream" in issues[0].message
    assert "feed_1..feed_3, and 1 of them is piped" in issues[0].message


def test_the_singular_spelling_of_a_family_is_not_counted():
    """Check that a one-feed column's unpiped feed is not counted."""
    fs = Flowsheet("col1")
    col = fs.add(U.Column("T-2"))
    fs.connect(col.overhead, fs.add(U.Product("D")).inlet)
    fs.connect(col.bottoms, fs.add(U.Product("B")).inlet)
    assert "feed_1" in col.ports and col.feed is col.feed_1
    assert _found(fs, "nozzle-unconnected") == []


def test_a_family_with_a_number_missing_is_listed_and_not_ranged():
    """Check that a numbered family with gaps is listed member by member, not ranged."""

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
    message = _found(fs, "nozzle-unconnected")[0].message
    assert "4 numbered nozzles, in_1, in_2, in_4 and in_7" in message
    assert ".." not in message


def test_a_spec_built_sheet_is_checked_too():
    """Check that a spec-built mixer's count is checked and survives a round trip."""
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
    assert "M-1.in_2 and M-1.in_3 carry no stream" in _found(fs, "nozzle-unconnected")[0].message
    assert [i.code for i in from_dict(fs.to_dict()).validate()] == [
        "nozzle-unconnected",
        "stream-table-missing",
    ]


@pytest.mark.parametrize(
    "build,bare",
    [
        (lambda fs: fs.add(U.HeatExchanger("E-1")), "tube_in"),
        (lambda fs: fs.add(U.Reactor("R-1")), "duty"),  # a duty
        (lambda fs: fs.add(U.Reactor("R-1")), "vent"),  # an off-gas
        (lambda fs: fs.add(U.Vessel("V-1")), "vent"),
        (lambda fs: fs.add(U.DistillationColumn("T-1")), "reboiler_duty"),
        (lambda fs: fs.add(U.Valve("HV-1")), "outlet"),  # a drain leg
        (lambda fs: fs.add(U.Separator("S-1")), "vapor"),
        (lambda fs: fs.add(U.Ejector("EJ-1")), "motive"),
        # The wash and the cake a cake-forming filter offers.
        (lambda fs: fs.add(U.Filter("F-1", variant="press")), "wash_in"),
        (lambda fs: fs.add(U.Filter("F-1", variant="press")), "cake"),
        (lambda fs: fs.add(U.Filter("F-1", variant="ion_exchange")), "regenerant_in"),
        (lambda fs: fs.add(U.Filter("F-1", variant="ion_exchange")), "spent_regenerant"),
    ],
)
def test_a_nozzle_the_class_declares_is_never_counted(build, bare):
    """A declared nozzle may remain unconnected without an unpiped finding."""
    fs = Flowsheet("declared")
    unit = build(fs)
    assert unit.ports[bare].stream is None
    assert _found(fs, "nozzle-unconnected") == []


def test_a_press_that_takes_no_wash_is_a_clean_sheet():
    """Check that a press with no wash validates clean, with or without its cake piped."""
    fs = Flowsheet("press")
    press = fs.add(U.Filter("F-301", variant="press"))
    fs.connect(fs.add(U.Feed("Slurry")).outlet, press.port("inlet")).properties = {
        "Flow (kg/h)": "4200"
    }
    fs.connect(press.port("outlet"), fs.add(U.Product("Filtrate")).inlet).properties = {
        "Flow (kg/h)": "4100"
    }
    assert [n for n in press.ports if press.ports[n].stream is None] == ["wash_in", "cake"]
    assert fs.validate() == []
    fs.connect(press.port("cake"), fs.add(U.Product("Cake")).inlet).properties = {
        "Flow (kg/h)": "100"
    }
    assert fs.validate() == []


def test_a_numbered_signal_family_is_out_of_scope():
    """Check that a numbered signal family is not reported while a process one is."""

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
    issues = _found(fs, "nozzle-unconnected")
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
    """Check which nozzle names _family_stem reads as a numbered family."""
    from pandid.validate import _family_stem

    assert _family_stem(name) == stem


@pytest.mark.parametrize(
    "build,stem,size",
    [
        (lambda: U.Mixer("M", n_inlets=4), "in", 4),
        (lambda: U.Splitter("S", n_outlets=3), "out", 3),
        (lambda: U.Column("T", n_feeds=2), "feed", 2),
        (lambda: U.Column("T", n_draws=3), "draw", 3),
        (lambda: U.Reactor("R", n_feeds=5), "feed", 5),
        (lambda: U.Block("B", inputs=["W", "N", "N"], outputs=1), "in", 3),
        (lambda: U.Block("B", inputs=1, outputs=2), "out", 2),
        (lambda: U.Tank("TK-1", inputs=3), "in", 3),
        (lambda: U.Vessel("V-1", inputs=2), "in", 2),
    ],
)
def test_every_counted_family_answers_to_the_naming_rule(build, stem, size):
    """Check that _family_stem finds every member of each counted nozzle family."""
    from pandid.validate import _family_stem

    unit = build()
    members = [n for n in unit.ports if _family_stem(n) == stem]
    assert len(members) == size


# --- material crossing an exchanger's sides -----------------------------------


def _exchanger(variant: str, *piped: str) -> Flowsheet:
    """Build E-101 with a feed on each piped inlet and a product on each piped outlet."""
    fs = Flowsheet("exchanger")
    hx = fs.add(U.HeatExchanger("E-101", variant=variant))
    for name in piped:
        port = hx.port(name)
        if port.direction == "inlet":
            fs.connect(fs.add(U.Feed(f"F-{name}")).outlet, port)
        else:
            fs.connect(port, fs.add(U.Product(f"P-{name}")).inlet)
    return fs


@pytest.mark.parametrize(
    ("variant", "fed", "drained", "a_out", "b_in"),
    [
        ("default", "shell_in", "tube_out", "shell_out", "tube_in"),
        ("plate", "side_a_in", "side_b_out", "side_a_out", "side_b_in"),
    ],
)
def test_material_crossing_an_exchangers_sides_is_reported(
    variant: str, fed: str, drained: str, a_out: str, b_in: str
):
    """Check that a feed on one side and an outlet on the other is reported once."""
    (issue,) = _found(_exchanger(variant, fed, drained), "exchanger-sides-crossed")
    assert issue.severity == "warning"
    assert issue.message.startswith(f"E-101 is fed at {fed} and drained at {drained}")
    assert f"fs.connect(E-101.{a_out}, P-{drained}.inlet)" in issue.message
    assert f"fs.connect(F-{fed}.outlet, E-101.{b_in})" in issue.message


@pytest.mark.parametrize(
    "piped",
    [("shell_in", "shell_out", "tube_in", "tube_out"), ("tube_in", "tube_out")],
    ids=["both sides", "tube side only"],
)
def test_an_exchanger_piped_side_by_side_is_not_reported(piped: tuple[str, ...]):
    """Check that each side carrying its own material is not reported."""
    assert _found(_exchanger("default", *piped), "exchanger-sides-crossed") == []


def test_crossed_sides_advice_names_flag_ports_as_connect_took_them():
    """Check that a flag's second line is named by the port typed, not outlet_2."""
    fs = Flowsheet("exchanger")
    feed, product = fs.add(U.Feed("F")), fs.add(U.Product("P"))
    hx = fs.add(U.HeatExchanger("E-101"))
    fs.connect(feed.outlet, fs.add(U.Product("Q")).inlet)
    fs.connect(fs.add(U.Feed("R")).outlet, product.inlet)
    fs.connect(feed.outlet, hx.shell_in)
    fs.connect(hx.tube_out, product.inlet)

    (issue,) = _found(fs, "exchanger-sides-crossed")
    assert "fs.connect(E-101.shell_out, P.inlet)" in issue.message
    assert "fs.connect(F.outlet, E-101.tube_in)" in issue.message


# --- nozzles crowded under their own arrowheads -------------------------------


def _fed_mixer(n_inlets=2, **box):
    """Build a laid-out mixer taking its *n_inlets* feeds on one face."""
    fs = Flowsheet("crowded")
    mix = fs.add(U.Mixer("M-1", n_inlets=n_inlets, **box))
    for i in range(1, n_inlets + 1):
        fs.connect(fs.add(U.Feed(f"F{i}")).outlet, mix.ports[f"in_{i}"])
    fs.connect(mix.outlet, fs.add(U.Product("P")).inlet)
    fs.layout()
    return fs, mix


def test_two_heads_without_the_paper_between_them_are_reported():
    from pandid.render.symbols import MIN_HEAD_CLEARANCE

    fs, _ = _fed_mixer(height=35)
    issues = _found(fs, "nozzles-crowded")
    assert [i.severity for i in issues] == ["warning"]
    assert "M-1.in_1 and M-1.in_2 are 14.0px apart on M-1's W face" in issues[0].message
    assert "leaves 2.0px of paper between two 12px arrowheads" in issues[0].message
    assert f"{MIN_HEAD_CLEARANCE:.0f}px ISO 128-20:1996 4.4" in issues[0].message
    assert "M-1.height = 40" in issues[0].message


def test_the_box_the_message_names_is_the_cure():
    """Check that the height the message suggests silences nozzles-crowded."""
    fs, _ = _fed_mixer(height=40)
    assert _found(fs, "nozzles-crowded") == []


def test_a_default_mixer_is_not_a_finding():
    """Check that a default-size two-inlet mixer is not reported crowded."""
    fs, _ = _fed_mixer()
    assert _found(fs, "nozzles-crowded") == []


@pytest.mark.parametrize("n_feeds", [2, 3])
@pytest.mark.parametrize("variant", ["default", "jacketed", "tubular"])
def test_a_stock_reactors_feeds_are_not_a_finding(variant: str, n_feeds: int):
    """Check that a stock reactor's two or three feeds are not reported crowded."""
    fs = Flowsheet("reactor")
    r = fs.add(U.Reactor("R-1", n_feeds=n_feeds, variant=variant))
    for i in range(1, n_feeds + 1):
        fs.connect(fs.add(U.Feed(f"F{i}")).outlet, r.ports[f"feed_{i}"])
    fs.connect(r.outlet, fs.add(U.Product("P")).inlet)
    fs.route()
    assert _found(fs, "nozzles-crowded") == []


def test_overlapping_heads_are_worded_as_the_overlap_they_are():
    """Check that overlapping arrowheads are reported as an overlap, not a negative gap."""
    fs, _ = _fed_mixer(n_inlets=4, height=50)
    issues = _found(fs, "nozzles-crowded")
    assert len(issues) == 1
    assert "overlaps two 12px arrowheads by 0.3px" in issues[0].message
    assert "the tightest of the 4 it carries there" in issues[0].message


def test_a_third_nozzle_on_one_face_is_still_one_finding():
    """Check that three crowded nozzles on one face make one finding."""
    fs, _ = _fed_mixer(n_inlets=3, height=35)
    issues = _found(fs, "nozzles-crowded")
    assert len(issues) == 1
    assert "the tightest of the 3 it carries there" in issues[0].message


def test_nozzles_that_carry_no_arrowhead_are_not_crowded():
    """Check that a splitter's outlets at the crowded pitch are not reported."""
    from pandid.portgeom import port_point

    fs = Flowsheet("splitter")
    sp = fs.add(U.Splitter("SP-1", n_outlets=2, height=35))
    fs.connect(fs.add(U.Feed("F")).outlet, sp.inlet)
    for i in (1, 2):
        fs.connect(sp.ports[f"out_{i}"], fs.add(U.Product(f"P{i}")).inlet)
    fs.layout()
    ys = [port_point(sp, sp.frame, f"out_{i}")[1] for i in (1, 2)]
    assert abs(ys[1] - ys[0]) == 14.0  # the pitch the mixer above is reported at
    assert _found(fs, "nozzles-crowded") == []


def test_a_p_and_id_draws_no_head_to_be_crowded_by():
    """Check that nozzles-crowded is reported on a PFD and not on a P&ID."""
    fs, _ = _fed_mixer(height=35)
    assert len(_found(fs, "nozzles-crowded", diagram="pfd")) == 1
    assert _found(fs, "nozzles-crowded", diagram="p&id") == []
    assert _found(fs, "nozzles-crowded", diagram="pid") == []  # the other spelling
    fs.to_svg(diagram="p&id")
    assert [w for w in fs.warnings if w.code == "nozzles-crowded"] == []
    assert "marker-end" not in fs.to_svg(diagram="p&id")
    fs.to_svg()
    assert len([w for w in fs.warnings if w.code == "nozzles-crowded"]) == 1


def test_the_floor_is_the_arrowhead_the_renderer_actually_draws():
    """Check that the floor matches the drawn arrowhead and twice the main flow width."""
    import re

    from pandid.render.weights import LineWeight
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
    assert MIN_HEAD_CLEARANCE == 2 * LineWeight.MAIN_FLOW.width
    assert MIN_NOZZLE_PITCH == ARROWHEAD + MIN_HEAD_CLEARANCE


def test_the_pitch_a_block_chooses_clears_the_floor_this_check_enforces():
    """Check that BLOCK_PITCH is at least MIN_NOZZLE_PITCH."""
    from pandid.render.symbols import BLOCK_PITCH, MIN_NOZZLE_PITCH

    assert BLOCK_PITCH >= MIN_NOZZLE_PITCH


def test_a_block_gathering_streams_onto_one_face_is_not_crowded():
    """Check that a block with many streams on one face is not reported crowded."""
    fs = Flowsheet("bfd")
    block = fs.add(U.Block("U-100", inputs=["W"] * 4 + ["N"] * 3, outputs=["E"] * 2 + ["S"] * 2))
    for i in range(1, 8):
        fs.connect(fs.add(U.Feed(f"F{i}")).outlet, block.ports[f"in_{i}"])
    for i in range(1, 5):
        fs.connect(block.ports[f"out_{i}"], fs.add(U.Product(f"P{i}")).inlet)
    fs.layout()
    assert _found(fs, "nozzles-crowded") == []


def _unit_classes():
    """Return every built-in Unit subclass, keyed by the ``kind`` its symbols answer to."""
    from pandid import units as unit_types

    out = {}
    for name in unit_types.__all__:
        cls = getattr(unit_types, name)
        if isinstance(cls, type) and issubclass(cls, U.Unit) and cls is not U.Unit:
            out.setdefault(cls.kind, cls)
    return out


#: Every registered (kind, variant) except boundary flags and instruments.
_REGISTERED = sorted(
    (kind, variant)
    for (kind, variant) in default_registry._symbols
    if kind not in ("feed", "product", "instrument")
)


@pytest.mark.parametrize("kind,variant", _REGISTERED, ids=lambda v: str(v))
def test_every_registered_symbol_is_quiet_on_a_nozzle_pinned_run(kind, variant):
    """Check that every registered in-line symbol is quiet on a correctly pinned run."""
    from pandid.portgeom import port_point

    cls = _unit_classes().get(kind)
    if cls is None:
        pytest.skip(f"{kind} has no built-in Unit class")
    unit = cls("U-1", **_drawing(cls, variant))
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
    assert _found(fs, "run-off-elevation") == []


# --- a balloon nothing could place --------------------------------------------


def _cyclic_balloons(pump_x=400, pump_y=100):
    """Build two balloons hung off each other, with P-1 pinned at *pump_x*, *pump_y*."""
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
    """Check that two balloons hosting each other are each an instrument-unplaced error."""
    fs = _cyclic_balloons()
    fs.layout()
    issues = _found(fs, "instrument-unplaced")
    assert [i.severity for i in issues] == ["error", "error"]
    assert sorted(i.message.split()[0] for i in issues) == ["LIC-1", "LT-1"]
    assert "hangs off LIC-1, which is unplaced itself" in issues[0].message
    assert "hangs off LT-1, which is unplaced itself" in issues[1].message
    assert "LT-1.attach(<stream or unit>)" in issues[0].message


def test_an_unplaced_balloon_does_not_blind_the_rest_of_the_sheet():
    """Check that unplaced balloons do not hide a unit overlap on the same sheet."""
    fs = _cyclic_balloons(pump_x=110, pump_y=110)
    fs.layout()
    codes = [i.code for i in fs.validate()]
    assert "unit-overlap" in codes
    assert codes.count("instrument-unplaced") == 2


def test_a_sheet_that_places_its_balloons_reports_nothing_here():
    """Check that balloons hung off placed hosts report no instrument-unplaced."""
    fs = Flowsheet("placed")
    tank = fs.add(U.Tank("T-1"))
    pump = fs.add(U.Pump("P-1"))
    fs.connect(tank.outlet, pump.suction)
    lt = fs.add_instrument("LT", 1, near=tank)
    fs.add_instrument("LIC", 1, near=lt, display="central")
    fs.layout()
    assert fs.unplaced_instruments == []
    assert _found(fs, "instrument-unplaced") == []


def test_it_is_not_reported_before_layout_has_run():
    """Check that instrument-unplaced is not reported before layout runs."""
    fs = _cyclic_balloons()
    assert _found(fs, "instrument-unplaced") == []


def test_a_balloon_tapping_a_line_with_an_unplaced_end_names_the_line():
    """Check that a balloon on a line with an unplaced end names that line."""
    fs = _cyclic_balloons()
    by_name = {u.name: u for u in fs.units}
    sig = fs.connect(by_name["LT-1"].sig_out, by_name["LIC-1"].sig_in, kind="electric")
    fs.add_instrument("LY", 1, sensing=sig)
    fs.layout()
    ly = [i for i in _found(fs, "instrument-unplaced") if i.message.startswith("LY-1")]
    assert len(ly) == 1
    assert f"hangs off stream {sig.name}, which has an end nothing placed" in ly[0].message


def test_render_refuses_the_sheet_by_the_finding_and_not_the_bounding_box():
    """Check that rendering an unplaced balloon raises instrument-unplaced."""
    fs = _cyclic_balloons()
    with pytest.raises(ValueError, match="instrument-unplaced"):
        fs.to_svg()


# --- stream-name-reused ---------------------------------------------------


def _collided() -> Flowsheet:
    """Build a sheet whose explicit stream name is a number the counter reaches."""
    fs = Flowsheet("collide", stream_number_start=100)
    feeds = [fs.add(U.Feed(f"F{i}")) for i in range(3)]
    m = fs.add(U.Mixer("M-1", n_inlets=3))
    fs.connect(feeds[0].outlet, m.inlets[0], name="S102")  # the third number
    fs.connect(feeds[1].outlet, m.inlets[1])
    fs.connect(feeds[2].outlet, m.inlets[2])
    return fs


def test_a_counted_name_landing_on_a_used_one_is_reported():
    found = _found(_collided(), "stream-name-reused")
    assert len(found) == 1
    assert "2 streams answer to 'S102'" in found[0].message
    assert "F2 to M-1" in found[0].message  # which run took the counted name


def test_the_reused_name_costs_a_stream_table_column():
    """Check that a reused stream name drops one stream-table column."""
    from pandid.render.furniture import _table_runs

    fs = _collided()
    assert len(_table_runs(fs)) == len(fs.streams) - 1
    assert _found(fs, "stream-name-reused")


def test_a_run_drawn_in_segments_is_not_a_collision():
    """Check that one name given to two segments of a run is not reported."""
    fs = Flowsheet("segments")
    f = fs.add(U.Feed("F"))
    hx = fs.add(U.HeatExchanger("E-1"))
    p = fs.add(U.Product("P"))
    fs.connect(f.outlet, hx.tube_in, name="S-305")
    fs.connect(hx.tube_out, p.inlet, name="S-305")
    assert len(fs._stream_groups()) == 2
    assert _found(fs, "stream-name-reused") == []


def test_one_line_number_on_two_runs_is_not_a_collision():
    """Check that two runs with the same line number are not reported."""
    fs = Flowsheet("lines")
    f = fs.add(U.Feed("F"))
    hx = fs.add(U.HeatExchanger("E-1"))
    p = fs.add(U.Product("P"))
    a = fs.connect(f.outlet, hx.tube_in, size=6, service="P", spec="A1A", sequence=1001)
    b = fs.connect(hx.tube_out, p.inlet, size=6, service="P", spec="A1A", sequence=1001)
    assert a.name == b.name
    assert _found(fs, "stream-name-reused") == []


def test_a_plainly_numbered_sheet_reports_nothing():
    fs = Flowsheet("plain")
    f = fs.add(U.Feed("F"))
    v = fs.add(U.Valve("FV-1"))
    p = fs.add(U.Product("P"))
    fs.connect(f.outlet, v.inlet)
    fs.connect(v.outlet, p.inlet)
    assert _found(fs, "stream-name-reused") == []


# --- boundary-flow-missing ------------------------------------------------


def _partly_tabulated() -> Flowsheet:
    """Build a sheet that states properties on its inlet and on nothing else."""
    fs = Flowsheet("partly")
    feed = fs.add(U.Feed("Raw Feed"))
    pump = fs.add(U.Pump("P-101"))
    prod = fs.add(U.Product("To Storage"))
    fs.connect(feed.outlet, pump.suction).properties = {"Flow (kg/h)": "4200"}
    fs.connect(pump.discharge, prod.inlet)
    return fs


def test_an_outgoing_line_with_nothing_on_it_is_reported():
    found = _found(_partly_tabulated(), "boundary-flow-missing")
    assert len(found) == 1
    assert found[0].message.startswith("S2 crosses the sheet edge at To Storage")
    assert "4.3.2 d)" in found[0].message


def test_the_reported_line_is_the_column_the_table_keeps_empty():
    """Check that the reported line is the stream-table column left empty."""
    from pandid.render.furniture import _table_runs

    fs = _partly_tabulated()
    kept = [run[0].name for run in _table_runs(fs) if not run[0].properties]
    assert kept == [i.message.split()[0] for i in _found(fs, "boundary-flow-missing")] == ["S2"]


def test_an_internal_line_with_nothing_on_it_is_not_reported():
    """Check that an internal line with no properties is not reported."""
    fs = Flowsheet("internal")
    feed = fs.add(U.Feed("Raw Feed"))
    pump = fs.add(U.Pump("P-101"))
    hx = fs.add(U.HeatExchanger("E-101"))
    prod = fs.add(U.Product("To Storage"))
    fs.connect(feed.outlet, pump.suction).properties = {"Flow (kg/h)": "4200"}
    fs.connect(pump.discharge, hx.tube_in)
    fs.connect(hx.tube_out, prod.inlet).properties = {"Flow (kg/h)": "4200"}
    assert _found(fs, "boundary-flow-missing") == []


def test_a_value_present_and_blank_is_a_report():
    """Check that an empty-string property counts as a stated value."""
    fs = _partly_tabulated()
    fs.streams[1].properties = {"Flow (kg/h)": ""}
    assert _found(fs, "boundary-flow-missing") == []


@pytest.mark.parametrize(("diagram", "reported"), [("pfd", 1), ("p&id", 0), ("bfd", 0)])
def test_only_a_pfd_owes_a_flow_on_every_boundary_line(diagram, reported):
    """Check that boundary-flow-missing is reported on a PFD alone."""
    fs = _partly_tabulated()
    assert len(_found(fs, "boundary-flow-missing", diagram=diagram)) == reported
    fs.to_svg(diagram=diagram, show_stream_table=True)
    assert len([w for w in fs.warnings if w.code == "boundary-flow-missing"]) == reported


def _table_columns(drawn: str) -> list[str]:
    """Return the stream names heading the table columns of an SVG or draw.io export."""
    if "<mxfile" in drawn:
        return re.findall(r'id="[^"]*-r0-c\d+"[^>]*value="(S\d+)"', drawn)
    tables = re.findall(r'<g id="stream_table[^"]*">.*?</g>', drawn, re.S)
    return re.findall(r">(S\d+)</text>", "".join(tables))


@pytest.mark.parametrize("draw", ["to_svg", "to_drawio"])
@pytest.mark.parametrize("table", [True, "sheet"])
@pytest.mark.parametrize(
    ("diagram", "columns"), [("pfd", ["S1", "S2"]), ("p&id", ["S1"]), ("bfd", ["S1"])]
)
def test_only_a_pfd_keeps_an_empty_column_for_a_boundary_line(draw, table, diagram, columns):
    """Check that the table keeps S2's empty boundary column on a PFD alone."""
    fs = _partly_tabulated()
    assert _table_columns(getattr(fs, draw)(diagram=diagram, show_stream_table=table)) == columns


# --- stream-table-missing --------------------------------------------------


def _untabulated() -> Flowsheet:
    """Build a PFD with material crossing its edge and no property anywhere."""
    fs = Flowsheet("untabulated")
    feed = fs.add(U.Feed("Raw Feed"))
    pump = fs.add(U.Pump("P-101"))
    prod = fs.add(U.Product("To Storage"))
    fs.connect(feed.outlet, pump.suction)
    fs.connect(pump.discharge, prod.inlet)
    return fs


def test_a_pfd_with_a_boundary_and_nothing_tabulated_is_reported():
    found = _found(_untabulated(), "stream-table-missing")
    assert len(found) == 1
    assert "4.3.2 d)" in found[0].message
    assert "S1" in found[0].message and "S2" in found[0].message
    assert found[0].message.startswith("S1 and S2 cross")


def test_an_internal_only_sheet_has_no_boundary_to_report():
    """Check that a sheet with no feed or product reports no stream-table-missing."""
    fs = Flowsheet("internal-loop")
    a = fs.add(U.Pump("P-101"))
    b = fs.add(U.HeatExchanger("E-101"))
    fs.connect(a.discharge, b.tube_in)
    assert _found(fs, "stream-table-missing") == []


def test_a_sheet_that_has_started_tabulating_is_boundary_flow_missings_to_report():
    """Check that one stated property swaps stream-table-missing for boundary-flow-missing."""
    fs = _untabulated()
    fs.streams[0].properties = {"Flow (kg/h)": "4200"}
    assert _found(fs, "stream-table-missing") == []
    assert len(_found(fs, "boundary-flow-missing")) == 1  # S2 is the column left empty


@pytest.mark.parametrize("diagram", ["p&id", "bfd"])
def test_a_pid_or_a_bfd_is_not_reported(diagram):
    """Check that the sheet as a P&ID or a BFD has no findings and renders without warnings."""
    fs = _untabulated()
    assert fs.validate(diagram=diagram) == []
    fs.to_svg(diagram=diagram)
    assert fs.warnings == []


# --- stream-table-undrawn --------------------------------------------------


def _tabulated() -> Flowsheet:
    """Build a PFD that states a flow on both of its lines."""
    fs = _untabulated()
    for s in fs.streams:
        s.properties = {"Flow (kg/h)": "4200"}
    return fs


def _undrawn(fs: Flowsheet) -> list:
    """Return the stream-table-undrawn findings of the last render."""
    return [w for w in fs.warnings if w.code == "stream-table-undrawn"]


@pytest.mark.parametrize("draw", ["to_svg", "to_drawio"])
def test_a_pfd_drawn_without_the_table_its_flows_need_is_reported(draw):
    fs = _tabulated()
    getattr(fs, draw)()
    (found,) = _undrawn(fs)
    assert found.severity == "warning"
    assert found.message.startswith("S1 and S2 state properties")
    assert "4.3.2 d)" in found.message
    assert "render(show_stream_table=True)" in found.message
    assert _found(fs, "stream-table-undrawn") == [found]


def test_validate_answers_for_the_table_it_is_told_about():
    """Check that validate() follows show_stream_table, or the last render's."""
    fs = _tabulated()
    assert _found(fs, "stream-table-undrawn") == []
    assert len(_found(fs, "stream-table-undrawn", show_stream_table=False)) == 1
    fs.to_svg(show_stream_table=True)
    assert _found(fs, "stream-table-undrawn") == []
    with pytest.raises(ValueError, match="show_stream_table='sheets'"):
        fs.validate(show_stream_table=cast(Any, "sheets"))


@pytest.mark.parametrize(
    ("diagram", "table"),
    [("pfd", True), ("pfd", "sheet"), ("p&id", False), ("bfd", False)],
)
def test_a_drawn_table_or_a_sheet_that_owes_none_is_not_reported(diagram, table):
    """Check that a drawn table, a P&ID and a BFD report no stream-table-undrawn."""
    fs = _tabulated()
    fs.to_svg(diagram=diagram, show_stream_table=table)
    assert _undrawn(fs) == []


def test_an_undrawn_table_takes_the_place_of_its_empty_column():
    """Check that an undrawn table reports no boundary-flow-missing column."""
    fs = _partly_tabulated()
    fs.to_svg()
    assert [w.code for w in fs.warnings] == ["stream-table-undrawn"]


def test_the_bfd_owes_no_table_and_heads_its_lines_all_the_same():
    """Check each diagram kind's answers on arrowheads and boundary-flow tabulation."""
    from pandid.render.svg import draws_arrowheads, tabulates_boundary_flows

    answers = {
        kind: (draws_arrowheads(kind), tabulates_boundary_flows(kind))
        for kind in ("pfd", "p&id", "bfd")
    }
    assert answers == {
        "pfd": (True, True),  # heads its lines, and 4.3.2 d) is its clause
        "p&id": (False, False),  # neither: 4.4.2
        "bfd": (True, False),  # heads its lines (4.2.2 c)), owes no rate
    }


@pytest.mark.parametrize(
    ("build", "code", "render"),
    [
        (_collided, "stream-name-reused", {}),
        (_partly_tabulated, "boundary-flow-missing", {"show_stream_table": True}),
        (_untabulated, "stream-table-missing", {}),
    ],
)
def test_a_soft_finding_is_a_warning_and_the_sheet_still_draws(build, code, render):
    """Check that each of these findings is a warning and the sheet still renders."""
    fs = build()
    assert [i.severity for i in _found(fs, code)] == ["warning"]
    fs.to_svg(**render)


# --- energy-carrier-missing ------------------------------------------------


def heat_integrated(fs: Flowsheet | None = None, **connect: Any) -> tuple[Flowsheet, Stream]:
    """Build a sheet whose cooler passes its duty to its heater."""
    if fs is None:
        fs = Flowsheet("heat")
    feed = fs.add(U.Feed("F"))
    cooler = fs.add(U.Cooler("E-2"))
    heater = fs.add(U.Heater("E-1"))
    product = fs.add(U.Product("P"))
    fs.connect(feed.outlet, cooler.inlet)
    fs.connect(cooler.outlet, heater.inlet)
    fs.connect(heater.outlet, product.inlet)
    duty = fs.connect(cooler.utility_out, heater.utility_in, **connect)
    assert duty.kind == "energy"
    return fs, duty


def _drawn_label(fs: Flowsheet, text: str) -> bool:
    """Return whether a label drawn on the sheet contains *text*."""
    return re.search(rf">[^<]*{re.escape(text)}[^<]*</text>", fs.to_svg()) is not None


def test_an_energy_line_that_names_no_carrier_is_reported_on_a_pfd():
    fs, duty = heat_integrated()
    (found,) = _found(fs, "energy-carrier-missing")
    assert found.severity == "warning"
    assert found.message.startswith(f"{duty.name}, the energy line from E-2 to E-1,")
    assert "4.3.2 e)" in found.message


@pytest.mark.parametrize(
    ("connect", "diagram"),
    [
        ({"service": "LP steam"}, "pfd"),
        ({"name": "LP steam", "service": "LP steam"}, "pfd"),
        ({}, "p&id"),
        ({}, "bfd"),
    ],
)
def test_an_energy_line_is_not_reported_once_its_carrier_is_drawn_or_off_a_pfd(connect, diagram):
    """Check a drawn carrier, a P&ID and a BFD each leave the finding quiet."""
    fs, _ = heat_integrated(**connect)
    assert _found(fs, "energy-carrier-missing", diagram=diagram) == []


# Every keyword=value a finding spells, quoted as Python writes it.
_ADVISED = re.compile(r"""(\w+)=('(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")""")
_AUTHORED = {"sequence": "42", "spec": "CS"}


@pytest.mark.parametrize(
    ("scheme", "connect"),
    [
        (None, {}),
        (None, _AUTHORED),
        (None, {"name": "Q-1", **_AUTHORED}),
        (None, {"name": "Q-1", "service": "cooling water", **_AUTHORED}),
        ("{size}-{sequence}", {"service": "cooling water", **_AUTHORED}),
        ("{size}-{sequence}", _AUTHORED),
    ],
    ids=[
        "unset",
        "unset-with-fields",
        "unset-under-a-given-name",
        "hidden-by-a-given-name",
        "left-out-of-the-scheme",
        "unset-and-left-out-of-the-scheme",
    ],
)
def test_following_the_advice_draws_the_carrier_and_keeps_what_was_typed(scheme, connect):
    """Check the advice, applied as written, clears the finding and discards nothing."""
    fs = Flowsheet("heat") if scheme is None else Flowsheet("heat", line_numbering_scheme=scheme)
    fs, _ = heat_integrated(fs, **connect)
    if "service" in connect:
        assert not _drawn_label(fs, connect["service"])
    (found,) = _found(fs, "energy-carrier-missing")
    advice = {key: ast.literal_eval(value) for key, value in _ADVISED.findall(found.message)}
    assert advice, found.message
    scheme = advice.pop("line_numbering_scheme", scheme)
    fs = Flowsheet("heat") if scheme is None else Flowsheet("heat", line_numbering_scheme=scheme)
    fs, duty = heat_integrated(fs, **{**connect, **advice})
    assert _found(fs, "energy-carrier-missing") == []
    assert _drawn_label(fs, str(duty.service))
    for key, value in connect.items():
        assert value in str(getattr(duty, key)), f"{key}={value!r} lost: {found.message}"


# --- validate() answers about the sheet that was drawn ------------------------


def test_a_bare_validate_follows_the_drawing_that_was_made():
    fs = _untabulated()
    fs.to_svg(diagram="p&id")
    assert _found(fs, "stream-table-missing") == []
    fs.to_svg(diagram="pfd")
    assert len(_found(fs, "stream-table-missing")) == 1


def test_a_diagram_named_at_the_call_still_wins():
    """Check that a diagram named to validate() overrides the last render's."""
    fs = _untabulated()
    fs.to_svg(diagram="p&id")
    assert len(fs.validate(diagram="pfd")) == 1
    assert fs.validate(diagram="bfd") == []


def test_the_render_leaves_the_findings_a_bare_validate_then_makes():
    """Check that a bare validate() after a render matches that render's warnings."""
    fs = _untabulated()
    for kind in ("pfd", "p&id", "bfd"):
        fs.to_svg(diagram=kind)
        assert [str(i) for i in fs.validate()] == [str(w) for w in fs.warnings]


def test_an_unchecked_render_still_says_which_drawing_it_made():
    """Check that a check=False render still sets the diagram a bare validate() uses."""
    fs = _untabulated()
    fs.to_svg(diagram="p&id", check=False)
    assert _found(fs, "stream-table-missing") == []


def test_a_drawing_the_renderer_refused_is_not_remembered_as_the_one_made():
    """Check that a refused diagram leaves a bare validate() answering as a PFD."""
    fs = _untabulated()
    with pytest.raises(ValueError):
        fs.to_svg(diagram="isometric")
    assert len(_found(fs, "stream-table-missing")) == 1


# --- the model is checked before any geometry is built ------------------------


class _GeometryRan(AssertionError):
    """Error raised in place of layout or routing."""


@pytest.fixture
def no_geometry(monkeypatch):
    """Make ``layout()`` and ``route()`` raise ``_GeometryRan`` instead of running."""

    def refuse(self, *args, **kwargs):
        raise _GeometryRan("layout/route ran before the model was checked")

    monkeypatch.setattr(Flowsheet, "layout", refuse)
    monkeypatch.setattr(Flowsheet, "route", refuse)


def _off_sheet(value=float("nan"), axis="x"):
    """Build a three-unit run whose middle unit is pinned at *value* on *axis*."""
    fs = Flowsheet("not-finite")
    f = fs.add(U.Feed("F")).pin(x=60, y=100)
    hx = fs.add(U.HeatExchanger("E-101"))
    hx.pin_ = Pin(**{axis: value, "y" if axis == "x" else "x": 100})
    p = fs.add(U.Product("P")).pin(x=600, y=100)
    fs.connect(f.outlet, hx.tube_in)
    fs.connect(hx.tube_out, p.inlet)
    return fs


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("axis", ["x", "y"])
def test_a_pin_that_is_not_a_number_is_an_error(value, axis):
    """Check that a NaN or infinite pin on either axis is a pin-not-finite error."""
    issues = _found(_off_sheet(value, axis), "pin-not-finite")
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
    """Check that render() to .svg or .drawio refuses a non-finite pin and writes nothing."""
    out = tmp_path / f"sheet{suffix}"
    with pytest.raises(ValueError, match="pin-not-finite"):
        _off_sheet().render(out)
    assert not out.exists()


def test_the_model_error_is_the_one_reported(no_geometry):
    """Check that a sheet with a bad pin and an overlap is refused for the pin."""
    fs = Flowsheet("both")
    a = fs.add(U.Tank("T-1"))
    a.pin_ = Pin(x=float("nan"), y=100)
    b = fs.add(U.Pump("P-1")).pin(x=100, y=100)
    fs.add(U.Tank("T-2")).pin(x=100, y=100)
    fs.connect(a.outlet, b.suction)
    with pytest.raises(ValueError) as caught:
        fs.to_svg()
    assert "pin-not-finite" in str(caught.value)
    assert "unit-overlap" not in str(caught.value)


def test_check_false_skips_the_model_check_too(no_geometry):
    """Check that check=False skips the model check and reaches layout."""
    with pytest.raises(_GeometryRan):
        _off_sheet().to_svg(check=False)


def test_a_sound_model_still_reaches_the_geometry(no_geometry):
    """Check that a clean model passes the model check and reaches layout."""
    fs = Flowsheet("clean")
    f = fs.add(U.Feed("F"))
    p = fs.add(U.Product("P"))
    fs.connect(f.outlet, p.inlet)
    with pytest.raises(_GeometryRan):
        fs.to_svg()


def test_the_two_halves_are_the_whole_of_validate():
    """Check that validate() is model_issues() plus geometry_issues(), errors first."""
    from pandid.validate import geometry_issues, model_issues, validate

    fs = _cyclic_balloons(pump_x=110, pump_y=110)  # overlap, and two loose balloons
    fs.layout()
    whole = validate(fs)
    halves = model_issues(fs) + geometry_issues(fs)
    assert sorted(str(i) for i in whole) == sorted(str(i) for i in halves)
    assert [i.severity for i in whole] == sorted(
        (i.severity for i in whole), key=lambda s: s != "error"
    )


# --- a variant no symbol draws ------------------------------------------------


def _misspelt(build: str) -> Flowsheet:
    """Build a Feed -> unit -> Product run whose unit names an unknown variant."""
    fs = Flowsheet("variant")
    feed = fs.add(U.Feed("F"))
    product = fs.add(U.Product("P"))
    if build == "valve":
        valve = fs.add(U.Valve("V-1", variant="gat"))
        fs.connect(feed.outlet, valve.inlet)
        fs.connect(valve.outlet, product.inlet)
    else:
        reactor = fs.add(U.Reactor("R-1", variant="plain"))
        fs.connect(feed.outlet, reactor.feed)
        fs.connect(reactor.outlet, product.inlet)
    return fs


_REGISTRY_SAYS = {
    "valve": "valve has no variant 'gat' (did you mean 'gate'?); registered valve variants: ",
    "reactor": "reactor has no variant 'plain'; registered reactor variants: default, jacketed, tubular",
}


@pytest.mark.parametrize(("build", "tag"), [("valve", "V-1"), ("reactor", "R-1")])
def test_an_unknown_variant_is_a_model_error(no_geometry, build, tag):
    """Check that validate() reports an unknown variant before any layout."""
    (issue,) = _found(_misspelt(build), "variant-unknown")
    assert issue.severity == "error"
    assert issue.message.startswith(f"{tag}: {_REGISTRY_SAYS[build]}")


@pytest.mark.parametrize("build", ["valve", "reactor"])
def test_to_svg_refuses_an_unknown_variant_before_layout(no_geometry, build):
    """Check that to_svg() refuses an unknown variant as a model error."""
    with pytest.raises(ValueError, match="variant-unknown") as caught:
        _misspelt(build).to_svg()
    assert _REGISTRY_SAYS[build] in str(caught.value)


@pytest.mark.parametrize("build", ["valve", "reactor"])
def test_check_false_refuses_an_unknown_variant_in_the_same_words(build):
    """Check that to_svg(check=False) raises the registry's message at layout."""
    with pytest.raises(ValueError) as caught:
        _misspelt(build).to_svg(check=False)
    assert str(caught.value).startswith(_REGISTRY_SAYS[build])


# --- a run drawn on the slant -------------------------------------------------


def _hand_routed(*waypoints):
    """Build a pump discharge routed through *waypoints*, its ends pinned."""
    fs = Flowsheet("via")
    f = fs.add(U.Feed("F"))
    p = fs.add(U.Pump("P-1")).pin(port="discharge", x=320, y=60)
    q = fs.add(U.Product("Q")).pin(port="inlet", x=440, y=60)
    fs.connect(f.outlet, p.suction)
    run = fs.connect(p.discharge, q.inlet).via(list(waypoints))
    fs.layout()
    fs.route()
    return fs, run


def test_a_single_via_waypoint_that_squares_nothing_up_is_reported():
    """Check that a via() point off both nozzle axes is a route-diagonal warning."""
    from pandid.layout.attach import stream_path

    fs, run = _hand_routed((320.0, 200.0))
    assert stream_path(run) == [(320.0, 60.0), (320.0, 200.0), (440.0, 60.0)]
    (found,) = _found(fs, "route-diagonal")
    assert found.severity == "warning"
    assert "(320, 200) to (440, 60)" in found.message
    assert "Add the corner it turns at, (440, 200)" in found.message


def test_the_corner_it_names_is_the_cure():
    fs, _ = _hand_routed((320.0, 200.0), (440.0, 200.0))
    assert [i.code for i in fs.validate() if i.code == "route-diagonal"] == []


def test_route_detour_cannot_see_a_diagonal():
    """Check that route-detour measures a diagonal as its squared-up corner."""

    def detour(fs):
        return next(i for i in fs.validate() if i.code == "route-detour").message

    assert detour(_hand_routed((320.0, 200.0))[0]) == detour(
        _hand_routed((320.0, 200.0), (440.0, 200.0))[0]
    )


def test_a_segment_crosses_a_box_on_the_slant_as_well_as_square():
    """Check that segment_crosses_box tests diagonal and orthogonal segments."""
    from pandid.layout.conflicts import segment_crosses_box

    box = (10.0, 10.0, 90.0, 90.0)
    assert segment_crosses_box((0, 0), (100, 100), box)
    assert segment_crosses_box((50, 50), (200, 120), box)
    assert not segment_crosses_box((80, -10), (110, 20), box)
    assert not segment_crosses_box((0, 20), (20, 0), box)
    assert not segment_crosses_box((120, 120), (95, 95), box)
    assert segment_crosses_box((50, 0), (50, 100), box)
    assert segment_crosses_box((0, 50), (100, 50), box)
    assert not segment_crosses_box((10, 0), (10, 100), box)
    assert not segment_crosses_box((0, 95), (100, 95), box)


# --- what the sheet drew but nothing said -------------------------------------


def test_a_label_side_nothing_places_is_refused_rather_than_topped():
    """Check that a misspelt label_pos is a label-pos-unknown error naming the fix."""
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
    """Check that every valid label side, None and empty raise no finding."""
    from pandid.render.svg import LABEL_POSITIONS

    for side in (*LABEL_POSITIONS, None, ""):
        fs = Flowsheet("sides")
        fs.add(U.Pump("P-1", label_pos=side))
        assert [i.code for i in fs.validate()] == [], side


def test_a_label_side_is_refused_before_anything_is_laid_out():
    """Check that model_issues() reports an unknown label side before layout."""
    from pandid.validate import model_issues

    fs = Flowsheet("early")
    fs.add(U.Pump("P-1", label_pos="centre"))
    assert all(u.frame is None for u in fs.units)
    found = model_issues(fs)
    assert [(i.severity, i.code) for i in found] == [("error", "label-pos-unknown")]
    assert "did you mean 'center'?" in found[0].message


def test_a_kind_with_no_artwork_is_named_rather_than_drawn_blank():
    """Check that an unregistered kind warns once, naming the closest kind."""

    class Widget(U.Unit):
        kind = "pumpp"

    fs = Flowsheet("blank")
    fs.add(Widget("X-1"))
    fs.add(Widget("X-2"))
    fs.to_svg()
    found = [w for w in fs.warnings if w.code == "symbol-kind-unknown"]
    assert len(found) == 1
    assert "X-1" in found[0].message
    assert "'pumpp'" in found[0].message
    assert "did you mean 'pump'?" in found[0].message
    assert "60x60" in found[0].message

    clean = Flowsheet("clean-kinds")
    f = clean.add(U.Feed("F"))
    p = clean.add(U.Product("P"))
    clean.connect(f.outlet, p.inlet)
    clean.to_svg()
    assert "symbol-kind-unknown" not in [w.code for w in clean.warnings]


def test_a_block_letters_its_name_out_of_a_box_it_was_given():
    """Check that a block name wider than its given width warns label-overruns-symbol."""
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
    """Check that a self-sized block does not warn label-overruns-symbol."""
    fs = Flowsheet("bfd-auto")
    a = fs.add(U.Block("Fermentation and Beer Stripping Section"))
    b = fs.add(U.Block("Recovery"))
    fs.connect(a.out_1, b.in_1)
    fs.to_svg()
    assert "label-overruns-symbol" not in [w.code for w in fs.warnings]


def test_warnings_describe_the_last_render_and_nothing_earlier():
    """Check that fs.warnings holds only the last render's findings."""
    fs = Flowsheet("stale")
    f = fs.add(U.Feed("F")).pin(x=60, y=100)
    p = fs.add(U.Product("P")).pin(x=400, y=100)
    fs.connect(f.outlet, p.inlet)
    fs.add_instrument("FCI", 1, near=f)  # out of ISO 15519-2 order

    fs.to_svg()
    assert "letter-sequence" in [w.code for w in fs.warnings]
    kept = list(fs.warnings)

    fs.to_svg(check=False)
    assert fs.warnings == []
    assert kept, "the copy is the caller's, and is untouched by the next render"

    fs.to_svg()
    fs.to_svg()
    assert [w.code for w in fs.warnings].count("letter-sequence") == 1


# --- a round mark drawn as an oval ---------------------------------------------


def _sized(name="R-1", **kw) -> Flowsheet:
    fs = Flowsheet("aspect")
    fs.add(U.Reactor(name, **kw))
    return fs


def test_the_box_that_shipped_a_seventy_percent_stretch_is_reported():
    """Check that an 80x100 stirred reactor is reported 70% out of aspect with a cure."""
    found = _found(_sized("M-301", n_feeds=2, width=80, height=100), "symbol-out-of-aspect")
    assert len(found) == 1
    assert found[0].severity == "warning"
    assert "M-301" in found[0].message
    assert "80x100" in found[0].message and "62x131.778" in found[0].message
    assert "70% out of shape" in found[0].message
    assert "ISO item 20.6 C0082" in found[0].message
    assert "M-301.width = 47.05" in found[0].message


def test_the_width_the_message_offers_is_the_one_that_silences_it():
    """Check that the width the message suggests silences symbol-out-of-aspect."""
    fs = _sized("M-301", n_feeds=2, width=80, height=100)
    sym = default_registry.for_unit(fs.units[0])
    fixed = _sized("M-301", n_feeds=2, width=sym.width / sym.height * 100, height=100)
    assert _found(fixed, "symbol-out-of-aspect") == []


@pytest.mark.parametrize("width,height", [(None, None), (72, 153), (124, 264), (36, 76.5)])
def test_a_box_of_the_symbols_own_shape_is_quiet(width, height):
    """Check that a box at the symbol's own aspect, or unsized, is not reported."""
    kw = {k: v for k, v in (("width", width), ("height", height)) if v is not None}
    assert _found(_sized("M-301", n_feeds=2, **kw), "symbol-out-of-aspect") == []


def test_a_quarter_turn_is_not_a_stretch():
    """Check that a quarter-turned reactor with swapped size is not out of aspect."""
    fs = Flowsheet("turned")
    rx = fs.add(U.Reactor("R-1", n_feeds=2))
    sym = default_registry.for_unit(rx)
    rx.pin(x=100, y=100, orientation=90)
    rx.width, rx.height = sym.height, sym.width
    assert _found(fs, "symbol-out-of-aspect") == []
    rx.pin(x=100, y=100, orientation=0)
    assert len(_found(fs, "symbol-out-of-aspect")) == 1


def test_a_boundary_flag_stretched_to_hold_its_label_is_not_reported():
    """Check that a feed flag widened by its label is not reported out of aspect."""
    fs = Flowsheet("pennant")
    f = fs.add(U.Feed("Cooling Water Supply Header", reference="P&ID-101"))
    p = fs.add(U.Product("P"))
    fs.connect(f.outlet, p.inlet)
    fs.to_svg()
    assert "symbol-out-of-aspect" not in [w.code for w in fs.warnings]


def test_a_body_whose_marks_are_lines_may_be_any_shape():
    """Check that stretched packed and trayed bodies are not reported out of aspect."""
    packed = _sized("R-301", internals="packing", width=90, height=200)
    assert _found(packed, "symbol-out-of-aspect") == []

    fs = Flowsheet("column")
    fs.add(U.Column("T-401", internals="valve_tray", trays=20, width=110, height=340))
    assert _found(fs, "symbol-out-of-aspect") == []


def test_the_motor_really_is_round_on_its_own_box_and_oval_off_it():
    """Check that the agitator motor is square on the reactor's box and 1.3x off it."""
    from pandid.render.iso_parts import agitator_overlays
    from pandid.validate import ROUND_PARTS

    for variant in ("default", "jacketed"):
        body = default_registry.get("reactor", variant)
        overlays = agitator_overlays("agitator", "reactor", variant)
        motor = next(o for o in overlays if (o.group, o.name) in ROUND_PARTS)
        rect_w, rect_h = motor.w * body.width, motor.h * body.height
        assert rect_w == pytest.approx(rect_h, rel=1e-9)
        # A box 30 % wider than the symbol's own.
        sym = default_registry.for_unit(U.Reactor("R-1", variant=variant))
        drawn_w, drawn_h = 1.3 * sym.width, sym.height
        stretched = (rect_w * drawn_w / sym.width) / (rect_h * drawn_h / sym.height)
        assert stretched == pytest.approx(1.3, rel=1e-9)


def test_it_answers_before_anything_is_laid_out():
    """Check that model_issues() reports symbol-out-of-aspect before layout."""
    from pandid.validate import model_issues

    fs = _sized("M-301", n_feeds=2, width=80, height=100)
    assert all(u.frame is None for u in fs.units)
    assert [i.code for i in model_issues(fs)].count("symbol-out-of-aspect") == 1


# --- parallel runs, ISO 10628-1 5.3.2 -----------------------------------------


def _parallel_pair(gap_px: float):
    """Build two laid-out parallel runs with centrelines *gap_px* apart."""
    fs = Flowsheet("parallel")
    a = fs.add(U.Feed("A")).pin(x=60, y=200)
    ap = fs.add(U.Product("AP")).pin(x=600, y=200)
    b = fs.add(U.Feed("B")).pin(x=60, y=200 + gap_px)
    bp = fs.add(U.Product("BP")).pin(x=600, y=200 + gap_px)
    fs.connect(a.outlet, ap.inlet)
    fs.connect(b.outlet, bp.inlet)
    fs.layout()
    return fs


def test_two_runs_without_the_paper_between_them_are_reported():
    """Check that main flow lines 5px apart are reported lines-crowded."""
    issues = _found(_parallel_pair(5.0), "lines-crowded")
    assert [i.severity for i in issues] == ["warning"]
    assert "run parallel at y 200 and 205" in issues[0].message
    assert "leaving 3.0px (0.75 mm) of paper between them" in issues[0].message
    assert "4px ISO 10628-1 5.3.2" in issues[0].message


def test_two_runs_far_enough_apart_are_not_a_finding():
    """Check that main flow lines 6px apart, the exact floor, are not reported."""
    assert _found(_parallel_pair(6.0), "lines-crowded") == []


def test_the_clearance_floor_is_twice_the_widest_rung_the_pair_is_drawn_on():
    """Check that the floor the message names is twice the main flow line width."""
    import re

    from pandid.render.weights import LineWeight

    (issue,) = _found(_parallel_pair(5.0), "lines-crowded")
    asked = float(re.search(r"under the ([\d.]+)px ISO 10628-1 5\.3\.2", issue.message).group(1))
    assert asked / LineWeight.MAIN_FLOW.width == pytest.approx(2.0)


def test_two_runs_that_only_meet_end_to_end_are_not_parallel_lines():
    """Check that nearby runs sharing no length are not reported crowded."""
    fs = Flowsheet("abut")
    a = fs.add(U.Feed("A")).pin(x=60, y=200)
    ap = fs.add(U.Product("AP")).pin(x=300, y=200)
    b = fs.add(U.Feed("B")).pin(x=400, y=206)
    bp = fs.add(U.Product("BP")).pin(x=640, y=206)
    fs.connect(a.outlet, ap.inlet)
    fs.connect(b.outlet, bp.inlet)
    fs.layout()
    assert _found(fs, "lines-crowded") == []


# --- a line drawn through the unit it connects to -----------------------------


def _exchanger_run() -> tuple[Flowsheet, U.HeatExchanger, U.Feed, U.Product]:
    """Build E-101 between a feed below it and a product to its right."""
    fs = Flowsheet("own unit")
    feed = fs.add(U.Feed("F")).pin(x=200, y=300)
    e = fs.add(U.HeatExchanger("E-101")).pin(x=300, y=100)
    prod = fs.add(U.Product("P")).pin(x=600, y=40)
    fs.connect(feed.outlet, e.shell_in)
    fs.connect(e.shell_out, prod.inlet)
    fs.route()
    return fs, e, feed, prod


def _own_unit_findings(fs: Flowsheet) -> list[str]:
    return [
        i.message
        for i in fs.validate()
        if i.code == "route-crosses-unit" and "drawn through" in i.message
    ]


def test_a_line_drawn_up_through_the_unit_it_runs_to_is_reported():
    """Check that a line run up through its unit to an N-face nozzle is reported."""
    fs, e, feed, _ = _exchanger_run()
    (x, _), (_, y) = port_point(e, e.frame, "shell_in"), port_point(feed, feed.frame, "outlet")
    fs.streams[0].via([(x, y)])

    (said,) = _own_unit_findings(fs)
    assert said.startswith("stream S1 is drawn through E-101, which it runs to")
    assert "E-101.shell_in" in said and "N face" in said


def test_a_line_that_leaves_through_the_wrong_face_of_its_source_is_reported():
    """Check that a line leaving an S-face nozzle up through its unit is reported."""
    fs, e, _, prod = _exchanger_run()
    (x, _), (_, y) = port_point(e, e.frame, "shell_out"), port_point(prod, prod.frame, "inlet")
    fs.streams[1].via([(x, y)])

    (said,) = _own_unit_findings(fs)
    assert said.startswith("stream S2 is drawn through E-101, which it leaves from")
    assert "E-101.shell_out" in said and "S face" in said


def test_a_diagonal_drawn_through_the_unit_it_runs_to_is_reported():
    """Check that a slanted via() leg through its unit to an N-face nozzle is reported."""
    fs, e, feed, _ = _exchanger_run()
    (x, y), (_, fy) = port_point(e, e.frame, "shell_in"), port_point(feed, feed.frame, "outlet")
    fs.streams[0].via([(x + 90, fy), (x + 90, y + 90)])

    (said,) = _own_unit_findings(fs)
    assert said.startswith("stream S1 is drawn through E-101, which it runs to")
    assert len(_found(fs, "route-diagonal")) == 1


def test_a_diagonal_that_clears_the_unit_it_runs_to_is_not_reported():
    """Check that a slanted via() leg past its unit's corner is not reported."""
    fs, e, feed, _ = _exchanger_run()
    (x, y), (_, fy) = port_point(e, e.frame, "shell_in"), port_point(feed, feed.frame, "outlet")
    fs.streams[0].via([(x + 120, fy), (x + 120, y + 90), (x, y - 60)])

    assert _own_unit_findings(fs) == []
    assert len(_found(fs, "route-diagonal")) == 1


def test_a_line_that_reaches_its_nozzle_from_the_nozzle_face_is_not_reported():
    """Check that lines reaching their nozzles from the nozzle face are not reported."""
    fs, *_ = _exchanger_run()
    assert _own_unit_findings(fs) == []


def test_a_line_leaving_along_the_top_of_a_round_shell_is_not_reported():
    """Check that a line leaving a round shell's top nozzle sideways is not reported."""
    fs = Flowsheet("round shell")
    feed = fs.add(U.Feed("F"))
    e = fs.add(Condenser("E-402", width=70, height=70)).pin(mirrored="y").pin(x=300, y=100)
    prod = fs.add(U.Product("P")).pin(port="inlet", x=500, y=pinned_y(e, "shell_out"))
    fs.connect(feed.outlet, e.shell_in)
    run = fs.connect(e.shell_out, prod.inlet)
    fs.route()
    run.via([port_point(e, e.frame, "shell_out")])
    assert _own_unit_findings(fs) == []


def test_a_branch_drawn_from_the_middle_of_its_tee_is_not_reported():
    """Check that a branch drawn from its tee's centre out its nozzle is not reported."""
    fs = Flowsheet("tee")
    tee = fs.add(U.Tee()).pin(x=300, y=200)
    side = fs.add(U.Product("B")).pin(x=500, y=400)
    fs.connect(fs.add(U.Feed("F")).pin(x=60, y=100).outlet, tee.inlet)
    fs.connect(tee.outlet, fs.add(U.Product("P")).pin(x=500, y=100).inlet)
    branch = fs.connect(tee.branch, side.inlet)
    fs.route()
    assert tee.frame is not None
    (x, _), (_, y) = port_point(tee, tee.frame, "branch"), port_point(side, side.frame, "inlet")
    branch.via([(x, tee.frame.y + tee.frame.h / 2), (x, y)])
    assert _own_unit_findings(fs) == []


def test_a_straight_line_drawn_through_the_unit_it_runs_to_is_reported():
    """Check that a straight via([]) line through its unit is reported."""
    fs = Flowsheet("direct")
    feed = fs.add(U.Feed("F")).pin(x=330, y=300)
    e = fs.add(U.HeatExchanger("E-101")).pin(x=300, y=100)
    fs.connect(feed.outlet, e.shell_in).via([])
    fs.to_svg()

    (said,) = _own_unit_findings(fs)
    assert said.startswith("stream S1 is drawn through E-101, which it runs to")


# --- a crossing on a nozzle, a line along a box edge --------------------------


def _crossing_from_nozzle(gap: float) -> Flowsheet:
    """Build a run into AP crossed by a second run *gap* px before AP's inlet."""
    fs = Flowsheet("nozzle crossing")
    a = fs.add(U.Feed("A")).pin(x=60, y=200)
    ap = fs.add(U.Product("AP")).pin(x=400, y=200)
    b = fs.add(U.Feed("B")).pin(x=60, y=60)
    bp = fs.add(U.Product("BP")).pin(x=600, y=340)
    fs.connect(a.outlet, ap.inlet)
    over = fs.connect(b.outlet, bp.inlet)
    fs.layout()
    assert ap.frame is not None and b.frame is not None and bp.frame is not None
    x = port_point(ap, ap.frame, "inlet")[0] - gap
    over.via([(x, port_point(b, b.frame, "outlet")[1]), (x, port_point(bp, bp.frame, "inlet")[1])])
    return fs


def test_a_crossing_inside_an_arrowhead_length_of_a_nozzle_is_reported():
    """Check that a line crossed 5px before the nozzle it runs to is reported."""
    (issue,) = _found(_crossing_from_nozzle(5.0), "route-crosses-near-nozzle")
    assert issue.severity == "warning"
    assert issue.message == "stream S2 crosses S1 5.0px from AP.inlet"


def test_a_crossing_an_arrowhead_length_clear_of_the_nozzle_is_not_reported():
    """Check that the same crossing 20px before the nozzle is not reported."""
    assert _found(_crossing_from_nozzle(20.0), "route-crosses-near-nozzle") == []


def _run_over_vessel(offset: float, balloon: bool = False, flag: bool = False) -> Flowsheet:
    """Build a run drawn *offset* px above V-1's box, its LT-1, or a corner-pinned flag Q."""
    from pandid.portgeom import drawn_box

    fs = Flowsheet("edge")
    v = fs.add(U.Vessel("V-1")).pin(x=300, y=200)
    lt = (
        fs.add_instrument("LT", 1, sensing=v, face="N")
        if balloon
        else fs.add(U.Product("Q")).pin(port=None, x=300, y=40)
        if flag
        else v
    )
    a = fs.add(U.Feed("A")).pin(x=60, y=100)
    ap = fs.add(U.Product("AP")).pin(x=700, y=100)
    run = fs.connect(a.outlet, ap.inlet)
    fs.layout()
    assert lt.frame is not None and a.frame is not None and ap.frame is not None
    top = drawn_box(lt, lt.frame)[1] - offset
    (ax, ay), (bx, by) = port_point(a, a.frame, "outlet"), port_point(ap, ap.frame, "inlet")
    run.via([(ax + 30, ay), (ax + 30, top), (bx - 30, top), (bx - 30, by)])
    return fs


def test_a_line_drawn_along_a_box_edge_is_reported():
    """Check that a run 1.5px off V-1's top edge is reported."""
    (issue,) = _found(_run_over_vessel(1.5), "route-along-unit")
    assert issue.severity == "warning"
    assert issue.message == (
        "stream S1 runs along the edge of V-1. Move V-1 clear of it: call .pin(x=..., y=...) on V-1"
    )


def test_a_line_along_a_balloon_says_how_to_move_the_balloon():
    """Check that a run along an attached balloon names attach(), not pin()."""
    (issue,) = _found(_run_over_vessel(1.5, balloon=True), "route-along-unit")
    assert issue.message.startswith("stream S1 runs along the edge of LT-1. LT-1 hangs off V-1")
    assert "call .attach(<the V-1 unit>, face=..., offset=...) on LT-1" in issue.message
    assert "pin(" not in issue.message


def _follow_pin(advice: str, unit: U.Unit, x: float, y: float) -> None:
    """Make the pin() call *advice* names for *unit*, with *x* and *y* in its blanks."""
    (args,) = re.findall(rf"call \.pin\(([^)]*)\) on {re.escape(unit.name)}(?![\w-])", advice)
    kwargs: dict[str, Any] = {}
    for arg in args.split(", "):
        key, value = arg.split("=")
        kwargs[key] = {"x": x, "y": y}[key] if value == "..." else ast.literal_eval(value)
    unit.pin(**kwargs)


def test_route_along_unit_advice_moves_a_corner_pinned_flag_by_its_corner():
    """Check that following the advice for a corner-pinned flag lands its corner there."""
    fs = _run_over_vessel(1.5, flag=True)
    (issue,) = _found(fs, "route-along-unit")
    flag = next(u for u in fs.units if u.name == "Q")
    _follow_pin(issue.message, flag, 500, 300)
    assert (pinned_x(flag), pinned_y(flag)) == (500, 300)


def test_unit_overlap_advice_moves_a_corner_pinned_flag_by_its_corner():
    """Check that following the overlap advice for a corner-pinned flag lands its corner there."""
    fs = Flowsheet("overlap")
    flag = fs.add(U.Feed("A")).pin(port=None, x=300, y=200)
    pump = fs.add(U.Pump("B"))
    fs.layout()
    assert flag.frame is not None and pump.frame is not None
    pump.frame = replace(pump.frame, x=flag.frame.x, y=flag.frame.y)
    _follow_pin(_overlap_message(fs), flag, 500, 300)
    assert (pinned_x(flag), pinned_y(flag)) == (500, 300)


def test_a_line_clear_of_a_box_edge_is_not_reported():
    """Check that a run 10px off V-1's top edge is not reported."""
    assert _found(_run_over_vessel(10.0), "route-along-unit") == []


def _run_over_flag(offset: float) -> Flowsheet:
    """Build a run drawn *offset* px above the top of the Air flag's pennant."""
    from pandid.render.svg import boundary_flag

    fs = Flowsheet("flag edge")
    air = fs.add(U.Feed("Air")).pin(x=300, y=200)
    a = fs.add(U.Feed("A")).pin(x=60, y=100)
    ap = fs.add(U.Product("AP")).pin(x=700, y=100)
    run = fs.connect(a.outlet, ap.inlet)
    fs.layout()
    assert air.frame is not None and a.frame is not None and ap.frame is not None
    top = boundary_flag(air, air.frame).box[1] - offset
    (ax, ay), (bx, by) = port_point(a, a.frame, "outlet"), port_point(ap, ap.frame, "inlet")
    run.via([(ax + 30, ay), (ax + 30, top), (bx - 30, top), (bx - 30, by)])
    return fs


def test_a_flag_is_measured_by_the_pennant_it_draws():
    """Check that a run inside a flag's box but clear of its pennant is not reported."""
    from pandid.portgeom import unit_box

    fs = _run_over_flag(14.0)
    air = next(u for u in fs.units if u.name == "Air")
    # The run is a pixel inside the top of the flag's box.
    assert air.frame is not None and unit_box(air, air.frame)[1] == 175.0
    assert _found(fs, "route-along-unit") == []
    assert len(_found(_run_over_flag(1.5), "route-along-unit")) == 1
