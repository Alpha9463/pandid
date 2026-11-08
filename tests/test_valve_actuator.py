"""Check the valve's two axes: what the body is, and what strokes it."""

import base64
import re
import urllib.parse
import warnings
import zlib

import pytest

from pandid import Flowsheet, devices, spec, units as U
from pandid.render.drawio import DrawioRenderer
from pandid.render.symbols import ACTUATORS, STEM_FOOT, actuator_art, default_registry
from test_symbol_invariants import _collect_segments, _nearest_distance

#: Every body that takes an actuator, with every actuator it takes.
_PAIRS = [
    (body, actuator)
    for body in STEM_FOOT
    for actuator in ACTUATORS
    if (body, actuator) != ("knife", "handwheel")
]
_IDS = [f"{body}-{actuator}" for body, actuator in _PAIRS]

#: The retired variants, and the body and actuator each draws.
_FUSED = {
    "control": ("default", "diaphragm"),
    "butterfly_pneumatic": ("butterfly", "diaphragm"),
    "motor": ("default", "motor"),
    "solenoid": ("default", "solenoid"),
    "hydraulic": ("default", "hydraulic"),
    "manual": ("default", "handwheel"),
}


def _drawn(body, actuator):
    return default_registry.for_unit(U.Valve("V-1", variant=body, actuator=actuator))


# --- the feature ------------------------------------------------------------


def test_a_ball_valve_takes_a_cylinder_actuator_on_its_stem():
    """Draw a 10 x 15 cylinder with its piston over the ball, the rod down to the ball's top."""
    sym = _drawn("ball", "piston")
    ball = default_registry.get("valve", "ball")
    assert (sym.width, sym.height) == (ball.width, ball.height + 15)
    assert '<rect x="7.25" y="0" width="10" height="15"' in sym.svg
    assert '<path d="M 7.25 7.5 L 17.25 7.5"' in sym.svg, "the piston, across the cylinder"
    assert '<path d="M 12.25 7.5 L 12.25 17.5"' in sym.svg, "the rod, onto the top of the ball"
    assert '<g transform="translate(0,15)">' in sym.svg, "the ball, under the cylinder"


@pytest.mark.parametrize("body, actuator", _PAIRS, ids=_IDS)
def test_every_body_takes_every_actuator_on_its_stem(body, actuator):
    """Land the stem on the body's own ink and keep the run where the body draws it."""
    plain = default_registry.get("valve", body)
    sym = _drawn(body, actuator)
    x = plain.ports["actuator"][0]
    rise = sym.height - plain.height
    ink = _collect_segments(f'<g transform="translate(0,{rise})">{plain.svg}</g>')
    foot = (x, rise + STEM_FOOT[body])
    assert _nearest_distance(foot, ink) <= 0.25, f"the stem lands in empty space at {foot}"
    stems = [
        (a, b)
        for a, b in _collect_segments(sym.svg)
        if a[0] == b[0] == x and max(a[1], b[1]) == pytest.approx(foot[1])
    ]
    assert any(min(a[1], b[1]) <= rise for a, b in stems), "no stem from the actuator to the body"
    assert sym.width == plain.width
    assert sym.ports["actuator"] == (x, 0.0), "the signal lands on the crown"
    for name, (px, py) in plain.ports.items():
        if name != "actuator":
            assert sym.ports[name] == (px, round(py + rise, 4))
            assert list(sym.port_faces[name]) == list(plain.port_faces[name])


@pytest.mark.parametrize("actuator", ACTUATORS)
def test_an_actuator_keeps_its_own_size_on_every_body(actuator):
    """Draw each actuator the same height over every body, whatever the body's size."""
    rises = {
        round(_drawn(body, actuator).height - default_registry.get("valve", body).height, 4)
        for body in STEM_FOOT
        if (body, actuator) != ("knife", "handwheel")
    }
    assert rises == {actuator_art(actuator, 0.0, 0.0)[1]}


@pytest.mark.parametrize("actuator", ACTUATORS)
def test_an_actuator_stays_inside_the_narrowest_body_s_box(actuator):
    """Keep every head inside the angle body's 19.75 width, its stem 7.5 from the left."""
    angle = default_registry.get("valve", "angle")
    art, _rise = actuator_art(actuator, angle.ports["actuator"][0], STEM_FOOT["angle"])
    xs = [x for segment in _collect_segments(f"<g>{art}</g>") for x, _ in segment]
    assert 0.0 <= min(xs) and max(xs) <= angle.width


# --- the retired spellings ---------------------------------------------------


@pytest.mark.parametrize("variant", sorted(_FUSED))
def test_a_retired_variant_warns_and_draws_its_body_and_actuator(variant):
    """Warn on a body-and-actuator variant and draw the body with the actuator."""
    body, actuator = _FUSED[variant]
    with pytest.warns(DeprecationWarning, match=f"variant='{variant}' is deprecated"):
        old = U.Valve("V-1", variant=variant)
    assert (old.variant, old.actuator_type) == (body, actuator)
    assert default_registry.for_unit(old) is _drawn(body, actuator)


def test_a_retired_variant_is_a_finding_on_the_sheet():
    fs = Flowsheet("retired")
    with pytest.warns(DeprecationWarning):
        fs.add(U.Valve("CV-1", variant="control"))
    assert [issue.code for issue in fs.validate()].count("deprecated") == 1


def test_a_retired_variant_with_another_actuator_is_refused():
    with pytest.raises(ValueError, match="one valve, two actuators"):
        U.Valve("V-1", variant="control", actuator="motor")


def test_the_gate_actuators_draw_the_heads_the_stencils_drew():
    """Draw the dome, the lettered boxes and the handwheel the retired variants drew."""
    dome = "M 7.25 5 A 5 5 0 0 1 12.25 0 A 5 5 0 0 1 17.25 5 Z"
    assert dome in _drawn("default", "diaphragm").svg
    for actuator, letter in (("motor", "M"), ("solenoid", "S"), ("hydraulic", "H")):
        svg = _drawn("default", actuator).svg
        assert '<rect x="4.75" y="0" width="15" height="7.5"' in svg
        assert '<path d="M 4.75 3.75 L 19.75 3.75"' in svg
        assert f'fill="#111">{letter}</text>' in svg
    assert '<path d="M 12.25 8.75 L 12.25 0 L 19.75 0"' in _drawn("default", "handwheel").svg


def test_the_device_classes_draw_their_actuator_on_any_body():
    """Draw a control, solenoid or motor-operated valve with its actuator on the body named."""
    assert devices.ControlValve("CV-1").actuator_type == "diaphragm"
    assert devices.ControlValve("CV-2", variant="globe").variant == "globe"
    assert devices.SolenoidValve("XV-1", variant="ball").actuator_type == "solenoid"
    assert devices.MotorOperatedValve("HV-1", variant="plug").actuator_type == "motor"


def test_a_device_class_draws_no_other_actuator():
    with pytest.raises(ValueError, match=r"build MotorOperatedValve\('XV-1'\)"):
        devices.SolenoidValve("XV-1", actuator="motor")


def test_a_device_class_takes_its_retired_variant_too():
    with pytest.warns(DeprecationWarning, match="butterfly_pneumatic"):
        valve = devices.ControlValve("CV-1", variant="butterfly_pneumatic")
    assert (valve.variant, valve.actuator_type) == ("butterfly", "diaphragm")


# --- refusals ----------------------------------------------------------------


@pytest.mark.parametrize("body", ["check", "relief", "psv", "regulator", "bleed"])
def test_a_body_with_no_stem_refuses_an_actuator(body):
    with pytest.raises(ValueError, match=f"variant '{body}' takes no actuator"):
        U.Valve("V-1", variant=body, actuator="piston")


def test_the_knife_body_refuses_a_second_handwheel():
    with pytest.raises(ValueError, match="draws its own handwheel"):
        U.Valve("V-1", variant="knife", actuator="handwheel")


def test_an_unknown_actuator_names_the_ones_there_are():
    with pytest.raises(ValueError, match="actuator is one of 'diaphragm', 'piston'"):
        U.Valve("V-1", actuator="pneumatic")


def test_a_misspelt_body_names_the_registered_ones():
    with pytest.raises(ValueError, match="did you mean 'globe'"):
        U.Valve("V-1", variant="glob", actuator="piston")


def test_the_actuator_is_keyword_only():
    """Check that ``actuator`` is keyword-only."""
    with pytest.raises(TypeError):
        U.Valve("CV-1", "gate", "diaphragm")  # pyright: ignore[reportCallIssue]


# --- normally closed ---------------------------------------------------------


#: Diaphragm valves main refused to show closed, and the spellings of each.
_REFUSED_CLOSED = [
    {"variant": "control"},
    {"actuator": "diaphragm"},
    {"variant": "gate", "actuator": "diaphragm"},
    {"variant": "globe", "actuator": "diaphragm"},
]


@pytest.mark.parametrize("spelling", _REFUSED_CLOSED, ids=lambda kw: "-".join(kw.values()))
def test_a_diaphragm_valve_main_refused_to_close_is_still_refused(spelling):
    """Refuse NC where main did, and on the bodies main drew no diaphragm on."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        with pytest.raises(ValueError, match=r"4\.2\.2\.10.*a diaphragm actuator"):
            U.Valve("CV-1", **spelling, normal_position="closed")


#: Spellings main drew as a closed pneumatic butterfly, lettered NC.
_ACCEPTED_CLOSED = [
    lambda: U.Valve("XV-1", variant="butterfly_pneumatic", normal_position="closed"),
    lambda: U.Valve("XV-1", variant="butterfly", actuator="diaphragm", normal_position="closed"),
    lambda: devices.ControlValve("XV-1", variant="butterfly_pneumatic", normal_position="closed"),
]


@pytest.mark.parametrize("build", _ACCEPTED_CLOSED, ids=["fused", "pair", "control_valve"])
def test_a_closed_pneumatic_butterfly_main_drew_still_draws_with_a_warning(build):
    """Draw it lettered NC, as main did, and warn that fail='closed' replaces it."""
    with pytest.warns(DeprecationWarning) as caught:
        valve = build()
    assert any("so use fail= alone" in str(w.message) for w in caught)
    assert valve.normal_position == "closed"
    fs = Flowsheet("nc")
    fs.add(valve).pin(x=100, y=100)
    assert ">NC</text>" in fs.to_svg()
    assert [i.code for i in fs.validate()].count("deprecated") >= 1


def test_closing_a_pneumatic_butterfly_later_warns_too():
    valve = U.Valve("XV-1", variant="butterfly", actuator="diaphragm")
    with pytest.warns(DeprecationWarning, match="use fail= alone"):
        valve.normal_position = "closed"
    assert valve.normal_position == "closed"


def test_a_normally_closed_actuated_valve_darkens_its_body_and_not_its_actuator():
    """Fill the body of a closed piston valve and leave its cylinder white."""
    closed = default_registry.for_unit(U.Valve("XV-1", actuator="piston", normal_position="closed"))
    assert closed.svg.count('fill="#111"') == 1
    assert '<rect x="7.25" y="0" width="10" height="15" fill="white"' in closed.svg
    assert closed.ports == _drawn("default", "piston").ports


# --- what the rest of the package reads off it -------------------------------


@pytest.mark.parametrize("actuator", ACTUATORS)
def test_the_actuator_round_trips_through_a_spec(actuator):
    """Write ``actuator:`` beside the body and read the same valve back."""
    fs = Flowsheet("round trip")
    fs.add(U.Valve("V-1", variant="globe", actuator=actuator))
    written = spec.to_dict(fs)
    assert (written["units"][0]["variant"], written["units"][0]["actuator"]) == ("globe", actuator)
    valve = Flowsheet.from_dict(written).units[0]
    assert isinstance(valve, U.Valve)
    assert (valve.variant, valve.actuator_type) == ("globe", actuator)


def test_a_device_class_writes_no_actuator_it_draws_anyway():
    fs = Flowsheet("round trip")
    fs.add(devices.ControlValve("CV-1"))
    assert "actuator" not in spec.to_dict(fs)["units"][0]


def test_a_retired_variant_in_a_spec_is_written_back_in_the_new_spelling():
    entry = {"kind": "Valve", "name": "XV-1", "variant": "butterfly_pneumatic"}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        fs = Flowsheet.from_dict({"name": "s", "units": [entry]})
    written = spec.to_dict(fs)["units"][0]
    assert (written["variant"], written["actuator"]) == ("butterfly", "diaphragm")


def test_a_balloon_over_a_valve_drops_its_signal_straight_onto_the_actuator(settled_gallery):
    """Draw FIC-604's and FIC-605's signals into their actuators with no jog."""
    fs = settled_gallery["13_tank_farm"][0]
    for line in ("S18", "S21"):
        stream = next(s for s in fs.streams if s.name == line)
        assert stream.route is not None
        assert len({x for x, _ in stream.route.waypoints}) == 1, stream.route.waypoints


def test_draw_io_draws_the_actuator_on_the_cell_and_the_body_under_it():
    """Export the actuator as the cell's outline and the body as a child in its own box."""
    fs = Flowsheet("drawio")
    valve = fs.add(U.Valve("XV-1", variant="ball", actuator="motor", normal_position="closed"))
    valve.pin(x=100, y=100)
    fs.layout()
    lines = DrawioRenderer().render(fs).splitlines()
    cell = next(line for line in lines if 'value="XV-1"' in line)
    assert "shape=stencil(" in cell and "ball_valve" not in cell
    at = next(i for i, line in enumerate(lines) if 'id="u0-body"' in line)
    assert "shape=mxgraph.pid.valves.ball_valve" in lines[at] and "fillColor=#111" in lines[at]
    # The 24.5 x 15 ball under the motor box's 7.5 rise.
    assert 'x="0" y="7.5" width="24.5" height="15"' in lines[at + 1]


#: The mark each actuator's draw.io outline draws on the default body.
_DRAWIO_MARKS = {
    "diaphragm": (
        '<move x="7.25" y="5"/><arc rx="5" ry="5" x-axis-rotation="0" large-arc-flag="0" '
        'sweep-flag="1" x="12.25" y="0"/><arc rx="5" ry="5" x-axis-rotation="0" '
        'large-arc-flag="0" sweep-flag="1" x="17.25" y="5"/><close/>'
    ),
    "piston": '<rect x="7.25" y="0" w="10" h="15"/><fillstroke/><path><move x="7.25" y="7.5"/>'
    '<line x="17.25" y="7.5"/>',
    **dict.fromkeys(
        ("motor", "solenoid", "hydraulic"),
        '<rect x="4.75" y="0" w="15" h="7.5"/><fillstroke/><path><move x="4.75" y="3.75"/>'
        '<line x="19.75" y="3.75"/>',
    ),
    "handwheel": '<move x="12.25" y="8.75"/><line x="12.25" y="0"/><line x="19.75" y="0"/>',
}

#: The letter each lettered box carries in draw.io.
_DRAWIO_LETTERS = {"motor": "M", "solenoid": "S", "hydraulic": "H"}


@pytest.mark.parametrize("actuator", ACTUATORS)
def test_draw_io_draws_each_actuator_s_own_mark(actuator):
    """Draw the dome, cylinder, lettered box or handwheel in the draw.io outline."""
    fs = Flowsheet("drawio")
    fs.add(U.Valve("V-1", actuator=actuator)).pin(x=100, y=100)
    fs.layout()
    cell = next(line for line in DrawioRenderer().render(fs).splitlines() if 'value="V-1"' in line)
    packed = re.search(r"shape=stencil\(([^)]*)\)", cell)
    assert packed is not None
    unpacked = zlib.decompressobj(-15).decompress(base64.b64decode(packed.group(1)))
    outline = urllib.parse.unquote(unpacked.decode("ascii"))
    assert _DRAWIO_MARKS[actuator] in outline
    letters = re.findall(r'<text str="(\w)"', outline)
    assert letters == [_DRAWIO_LETTERS[actuator]] if actuator in _DRAWIO_LETTERS else not letters


# --- advice that keeps what the author typed ---------------------------------


def test_a_class_refusal_names_the_class_with_every_other_argument():
    """Name the class that draws the actuator, keeping the body and the fail position."""
    with pytest.raises(ValueError) as caught:
        devices.SolenoidValve("XV-1", variant="ball", actuator="motor", fail="closed")
    assert "MotorOperatedValve('XV-1', variant='ball', fail='closed')" in str(caught.value)
    with pytest.raises(ValueError) as caught:
        devices.ControlValve("XV-2", variant="globe", actuator="piston", description="Vent")
    assert "Valve('XV-2', variant='globe', actuator='piston', description='Vent')" in str(
        caught.value
    )


def test_two_actuators_name_both_choices():
    with pytest.raises(ValueError, match="actuator='motor', or variant='control' alone"):
        U.Valve("V-1", variant="control", actuator="motor")


def test_the_knife_refusal_keeps_the_rest_of_the_call():
    with pytest.raises(ValueError, match="drop actuator='handwheel'"):
        U.Valve("V-1", variant="knife", actuator="handwheel", normal_position="closed")


def test_a_closed_pneumatic_butterfly_that_fails_open_keeps_both_letters():
    """Draw NC and FO as main did, and advise keeping fail='open' rather than reversing it."""
    with pytest.warns(DeprecationWarning) as caught:
        valve = U.Valve(
            "XV-1", variant="butterfly", actuator="diaphragm", normal_position="closed", fail="open"
        )
    advice = next(str(w.message) for w in caught if "normal_position='closed'" in str(w.message))
    assert "keep a fail position already given" in advice
    svg = _drawn_sheet(valve)
    assert ">NC</text>" in svg and ">FO</text>" in svg


def test_the_nc_refusal_keeps_a_fail_position_already_given():
    with pytest.raises(ValueError, match="keep a fail position already given"):
        U.Valve("CV-1", actuator="diaphragm", normal_position="closed", fail="open")


def _drawn_sheet(valve: U.Valve) -> str:
    fs = Flowsheet("one valve")
    fs.add(valve).pin(x=100, y=100)
    return fs.to_svg()


def test_a_body_the_class_cannot_draw_names_the_call_with_its_actuator():
    """Name a three-way body with the class's actuator, keeping the rest of the call."""
    with pytest.raises(ValueError) as caught:
        devices.ControlValve("FV-1", variant="three_way", fail="closed")
    assert "Valve('FV-1', variant='three_way', actuator='diaphragm', fail='closed')" in str(
        caught.value
    )
