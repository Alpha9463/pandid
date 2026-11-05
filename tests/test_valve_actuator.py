"""Check the valve's two axes: what the body is, and what strokes it."""

import pytest

from pandid import Flowsheet, devices, units as U
from pandid.render.symbols import ACTUATED, ACTUATORS, default_registry

# The dome and its stem from the "Pneumatic Operated" stencil.
_DOME = "A 20.0 20.0 0.0 0 1 49.0 0.0 A 20.0 20.0 0.0 0 1 69.0 20.0"
_STEM = "M 49.0 20.0 L 49.0 49.0"


def _art(variant):
    return default_registry.get("valve", variant).svg


# --- the defect --------------------------------------------------------------


def test_a_control_valve_draws_an_actuator():
    """Check that a control valve draws a diaphragm dome on a stem."""
    svg = _art("control")
    assert _DOME in svg, "no diaphragm dome on the variant named 'control'"
    assert _STEM in svg, "a dome with no stem is not mounted on anything"


def test_the_actuator_stands_above_the_body_rather_than_inside_it():
    """Check that the control valve's actuator stands above the body and the run."""
    sym = default_registry.get("valve", "control")
    assert (sym.width, sym.height) == (24.5, 19.75)
    # The run passes through the body under the dome, below the middle of the box.
    assert sym.ports["inlet"][1] == sym.ports["outlet"][1] == 12.4425
    assert sym.ports["inlet"][1] > sym.height / 2


def test_the_signal_still_lands_on_the_crown():
    """Check that the actuator nozzle is on the body's axis at the top."""
    sym = default_registry.get("valve", "control")
    assert sym.ports["actuator"] == (sym.width / 2, 0.0)


@pytest.mark.parametrize("variant", default_registry.variants("valve"))
def test_an_actuator_beside_the_axis_sits_exactly_on_it(variant: str):
    """Put an actuator a fraction of a pixel off the axis onto the axis."""
    sym = default_registry.get("valve", variant)
    x = sym.ports.get("actuator", (sym.width / 2, 0.0))[0]
    assert not 0 < abs(x - sym.width / 2) < 0.1, (x, sym.width)


def test_a_balloon_over_a_valve_drops_its_signal_straight_onto_the_actuator(settled_gallery):
    """Draw FIC-604's and FIC-605's signals into their actuators with no jog."""
    fs = settled_gallery["13_tank_farm"][0]
    for line in ("S18", "S21"):
        stream = next(s for s in fs.streams if s.name == line)
        assert stream.route is not None
        assert len({x for x, _ in stream.route.waypoints}) == 1, stream.route.waypoints


def test_the_old_drawing_keeps_its_place_under_its_own_name():
    """Check that the Saunders body draws its weir and no operator."""
    saunders = _art("saunders")
    assert _DOME not in saunders, "the Saunders body draws no operator"
    assert "A 25.0 25.0 0.0 0 1 69.0 18.0" in saunders, "the weir arc, inside the body"
    assert default_registry.get("valve", "saunders").height == 15.0


# --- the two axes ------------------------------------------------------------


def test_the_body_and_the_actuator_are_asked_for_separately():
    assert U.Valve("CV-1", variant="gate", actuator="diaphragm").variant == "control"
    assert (
        U.Valve("CV-2", variant="butterfly", actuator="diaphragm").variant == "butterfly_pneumatic"
    )
    assert U.Valve("XV-1", variant="gate", actuator="solenoid").variant == "solenoid"
    assert U.Valve("HV-1", variant="gate", actuator="handwheel").variant == "manual"


def test_control_is_the_shorthand_for_the_pairing_every_sheet_draws():
    """Check that ``control`` is the general body with a diaphragm."""
    assert (
        U.Valve("CV-1", variant="control").variant
        == U.Valve("CV-2", variant="default", actuator="diaphragm").variant
    )


def test_a_bare_body_is_still_a_bare_body():
    """Check that a body with no actuator draws none."""
    assert U.Valve("HV-1", variant="globe").variant == "globe"
    assert _DOME not in _art("globe")


@pytest.mark.parametrize("body,actuator", sorted(ACTUATED))
def test_every_pairing_names_a_drawing_that_exists(body, actuator):
    drawn = U.Valve("V-1", variant=body, actuator=actuator).variant
    assert drawn in default_registry.variants("valve")


def test_a_pairing_the_stencil_set_cannot_draw_is_refused():
    """Check that a pairing with no drawing is refused, listing the pairings there are."""
    with pytest.raises(ValueError, match=r"no symbol draws a 'globe' body"):
        U.Valve("CV-1", variant="globe", actuator="diaphragm")
    with pytest.raises(ValueError, match=r"variant='butterfly', actuator='diaphragm'"):
        U.Valve("CV-1", variant="globe", actuator="diaphragm")


def test_an_unknown_actuator_names_the_ones_there_are():
    with pytest.raises(ValueError, match=r"actuator is one of"):
        U.Valve("CV-1", variant="gate", actuator="piston")


def test_a_pairing_cannot_be_given_a_different_operator():
    """Check that a pairing given another operator is refused, naming its own."""
    with pytest.raises(
        ValueError, match=r"variant 'control' already draws a valve with a 'diaphragm' operator"
    ):
        U.Valve("CV-1", variant="control", actuator="motor")


#: ``(variant, actuator)`` for every pairing, read out of :data:`ACTUATED`.
_FITTED = sorted({(drawn, act) for (_, act), drawn in ACTUATED.items()})
_MISMATCHED = sorted(
    (drawn, act)
    for drawn in {d for d, _ in _FITTED}
    for act in ACTUATORS
    if (drawn, act) not in set(_FITTED)
)


@pytest.mark.parametrize("variant,actuator", _FITTED, ids=[f"{v}-{a}" for v, a in _FITTED])
def test_a_pairing_and_its_own_operator_resolve_to_the_pairing(variant, actuator):
    assert U.Valve("V-1", variant=variant, actuator=actuator).variant == variant


@pytest.mark.parametrize("variant,actuator", _MISMATCHED, ids=[f"{v}-{a}" for v, a in _MISMATCHED])
def test_a_pairing_and_somebody_else_s_operator_raise(variant, actuator):
    with pytest.raises(ValueError, match=r"one drawing, two operators"):
        U.Valve("V-1", variant=variant, actuator=actuator)


def test_the_actuator_is_keyword_only():
    """Check that ``actuator`` is keyword-only."""
    with pytest.raises(TypeError):
        U.Valve("CV-1", "gate", "diaphragm")


def test_the_pairing_is_not_stored_beside_the_drawing():
    """Check that a spec reads a pairing back as its drawing."""
    from pandid import spec

    fs = Flowsheet("round trip")
    fs.add(U.Valve("CV-1", variant="butterfly", actuator="diaphragm"))
    rebuilt = Flowsheet.from_dict(spec.to_dict(fs))
    assert rebuilt.units[0].variant == "butterfly_pneumatic"


def test_the_agreeing_pair_round_trips_too():
    """Check that a pairing with its own operator writes only the variant and reads back."""
    from pandid import spec

    fs = Flowsheet("round trip")
    fs.add(U.Valve("CV-303", variant="control", actuator="diaphragm"))
    written = spec.to_dict(fs)
    assert written["units"][0]["variant"] == "control"
    assert "actuator" not in written["units"][0]
    assert Flowsheet.from_dict(written).units[0].variant == "control"


# --- what the rest of the package reads off it -------------------------------


def test_an_actuated_valve_may_say_where_it_fails():
    """Check that an actuated valve takes ``fail=``."""
    assert U.Valve("CV-1", variant="gate", actuator="diaphragm", fail="closed").fail == "closed"
    assert U.Valve("CV-2", variant="butterfly", actuator="diaphragm", fail="open").fail == "open"


def test_a_handwheel_is_an_operator_and_not_an_actuator():
    """It loses no air, so there is no supply whose failure is the question."""
    with pytest.raises(ValueError, match=r"has no actuator"):
        U.Valve("HV-1", variant="gate", actuator="handwheel", fail="closed")


def test_a_control_valve_is_still_refused_the_normally_closed_mark():
    """Check that an actuated valve refuses ``normal_position="closed"``."""
    with pytest.raises(ValueError, match=r"4\.2\.2\.10"):
        U.Valve("CV-1", variant="gate", actuator="diaphragm", normal_position="closed")


def test_the_saunders_body_takes_the_letters_rather_than_the_fill():
    """Check that a normally closed Saunders valve is marked with the letters NC."""
    fs = Flowsheet("nc")
    fs.add(U.Valve("HV-1", variant="saunders", normal_position="closed")).pin(x=100, y=100)
    assert ">NC</text>" in fs.to_svg()


def test_the_device_class_draws_the_actuator_too():
    """Check that ``ControlValve`` resolves to the actuated drawings."""
    assert devices.ControlValve("CV-1").variant == "control"
    assert (
        devices.ControlValve("CV-2", variant="butterfly", actuator="diaphragm").variant
        == "butterfly_pneumatic"
    )


def test_a_device_class_takes_the_actuator_its_own_name_implies():
    """Check that a device class accepts the actuator its name implies."""
    assert devices.ControlValve("CV-1", actuator="diaphragm").variant == "control"
    assert (
        devices.ControlValve("CV-2", variant="control", actuator="diaphragm").variant == "control"
    )
    assert devices.SolenoidValve("XV-1", variant="solenoid", actuator="solenoid").variant == (
        "solenoid"
    )
    assert devices.MotorOperatedValve("HV-1", variant="motor", actuator="motor").variant == "motor"


# --- the removed spelling ----------------------------------------------------


def test_the_compound_body_name_survives_the_same_argument():
    """Check that ``butterfly_pneumatic`` is still a variant."""
    assert U.Valve("XV-1", variant="butterfly_pneumatic").variant == "butterfly_pneumatic"


def test_the_actuator_vocabulary_is_what_can_be_drawn():
    """Check that every actuator name has a drawing."""
    assert set(ACTUATORS) == {a for _, a in ACTUATED}
    assert "piston" not in ACTUATORS
