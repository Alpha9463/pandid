"""The valve's two axes: what the body is, and what strokes it.

Issue #136. ``Valve(variant="control")`` drew a Saunders body with nothing on
top of it -- a hand valve with a weir in it -- while the drawing that carried a
diaphragm actuator answered to ``pneumatic``, the signal medium. So the variant
an engineer types for a control valve drew the one thing a control valve cannot
be without, and the variant that drew it correctly was the one nobody would look
for.

**ISO 15519-2:2015 Table 5** (p. 19) settles that this is a defect and not a
style: it lists *"specific graphical symbols for process equipment incl. prime
movers ..., valves incl. actuators, connections, etc."* as **basic** information
for a P&ID. ``professional_examples/P&ID_301.pdf`` draws the dome on all six of
its control valves.

**Table A.3** of the same standard is where the two axes come from. It registers
the bowtie on its own (A.3.01, 2101A), registers the actuators on their own
(A.3.40-A.3.45), and then registers the control valve as the two together
(A.3.20, *"shown with general actuator"*, carrying 2101A, 210A and P050B at
once).
"""

import pytest

from pandid import Flowsheet, devices, units as U
from pandid.deprecation import CODE
from pandid.render.symbols import ACTUATED, ACTUATORS, default_registry

# The dome and its stem, out of the "Pneumatic Operated" stencil: two quarter
# arcs closing on the body's crown, then the stem down into the body. Matched as
# artwork rather than as a variant name, because the whole of #136 is that the
# name and the drawing had come apart.
_DOME = "A 20.0 20.0 0.0 0 1 49.0 0.0 A 20.0 20.0 0.0 0 1 69.0 20.0"
_STEM = "M 49.0 20.0 L 49.0 49.0"


def _art(variant):
    return default_registry.get("valve", variant).svg


# --- the defect --------------------------------------------------------------


def test_a_control_valve_draws_an_actuator():
    """The whole of #136, in one assertion."""
    svg = _art("control")
    assert _DOME in svg, "no diaphragm dome on the variant named 'control'"
    assert _STEM in svg, "a dome with no stem is not mounted on anything"


def test_the_actuator_stands_above_the_body_rather_than_inside_it():
    """A Saunders weir is *in* the bowtie; an actuator sits on top of it, and the
    difference is whether the symbol is 15 tall or 19.8."""
    sym = default_registry.get("valve", "control")
    assert (sym.width, sym.height) == (24.5, 19.8)
    # The run passes through the body, which is under the dome -- so the nozzles
    # are below the middle of the box, not on it.
    assert sym.ports["inlet"][1] == sym.ports["outlet"][1] == 12.4
    assert sym.ports["inlet"][1] > sym.height / 2


def test_the_signal_still_lands_on_the_crown():
    """Where a controller's output terminates is the top of the actuator, which
    is the top of the symbol whether or not an actuator is drawn there."""
    sym = default_registry.get("valve", "control")
    assert sym.ports["actuator"] == (12.2, 0.0)


def test_the_old_drawing_keeps_its_place_under_its_own_name():
    """A weir under a diaphragm is a real valve body. What it is not is a
    control valve, so it is a body style like any other."""
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
    """``variant="control"`` and the pair spelled out are one drawing, so an
    engineer who types the obvious thing gets the complete valve."""
    assert (
        U.Valve("CV-1", variant="control").variant
        == U.Valve("CV-2", variant="default", actuator="diaphragm").variant
    )


def test_a_bare_body_is_still_a_bare_body():
    """The actuator is not defaulted onto anything. A drawing that does not say
    what strokes the valve is the honest drawing for a hand valve in a line."""
    assert U.Valve("HV-1", variant="globe").variant == "globe"
    assert _DOME not in _art("globe")


@pytest.mark.parametrize("body,actuator", sorted(ACTUATED))
def test_every_pairing_names_a_drawing_that_exists(body, actuator):
    drawn = U.Valve("V-1", variant=body, actuator=actuator).variant
    assert drawn in default_registry.variants("valve")


def test_a_pairing_the_stencil_set_cannot_draw_is_refused():
    """The draw.io set fuses body and operator into one shape, so a globe under
    a diaphragm is not a drawing that exists. Refused, and the refusal lists
    what does -- the reader is holding a body the set draws and an actuator it
    draws, and has no way to know which of the two is the reason."""
    with pytest.raises(ValueError, match=r"no symbol draws a 'globe' body"):
        U.Valve("CV-1", variant="globe", actuator="diaphragm")
    with pytest.raises(ValueError, match=r"variant='butterfly', actuator='diaphragm'"):
        U.Valve("CV-1", variant="globe", actuator="diaphragm")


def test_an_unknown_actuator_names_the_ones_there_are():
    with pytest.raises(ValueError, match=r"actuator is one of"):
        U.Valve("CV-1", variant="gate", actuator="piston")


def test_a_pairing_cannot_be_given_a_second_operator():
    """``control`` already answers "what strokes it", so a second answer is a
    contradiction rather than a refinement and is not merged silently."""
    with pytest.raises(ValueError, match=r"already draws a valve with an operator"):
        U.Valve("CV-1", variant="control", actuator="motor")


def test_the_actuator_is_keyword_only():
    """Positionally it would land in ``width``, which is a silent wrong drawing
    rather than an error."""
    with pytest.raises(TypeError):
        U.Valve("CV-1", "gate", "diaphragm")


def test_the_pairing_is_not_stored_beside_the_drawing():
    """One fact, one place. The variant is what the sheet is issued with, so a
    round trip through a spec keeps the drawing and not the spelling."""
    from pandid import spec

    fs = Flowsheet("round trip")
    fs.add(U.Valve("CV-1", variant="butterfly", actuator="diaphragm"))
    rebuilt = Flowsheet.from_dict(spec.to_dict(fs))
    assert rebuilt.units[0].variant == "butterfly_pneumatic"


# --- what the rest of the package reads off it -------------------------------


def test_an_actuated_valve_may_say_where_it_fails():
    """ANSI/ISA-5.1 note 5.3.4(10) scopes the failure symbols to control valves
    and actuators, and now the drawing agrees with the list: everything that
    takes a ``fail`` has a powered actuator drawn on it."""
    assert U.Valve("CV-1", variant="gate", actuator="diaphragm", fail="closed").fail == "closed"
    assert U.Valve("CV-2", variant="butterfly", actuator="diaphragm", fail="open").fail == "open"


def test_a_handwheel_is_an_operator_and_not_an_actuator():
    """It loses no air, so there is no supply whose failure is the question."""
    with pytest.raises(ValueError, match=r"has no actuator"):
        U.Valve("HV-1", variant="gate", actuator="handwheel", fail="closed")


def test_a_control_valve_is_still_refused_the_normally_closed_mark():
    """PIP PIC001 4.2.2.10. It was refused on the strength of being a control
    valve while drawing something else; it is refused now on the strength of the
    drawing."""
    with pytest.raises(ValueError, match=r"4\.2\.2\.10"):
        U.Valve("CV-1", variant="gate", actuator="diaphragm", normal_position="closed")


def test_the_saunders_body_takes_the_letters_rather_than_the_fill():
    """Its weir is inside the outline and a filled body swallows it, which is
    clause 4.2.2.8's case."""
    fs = Flowsheet("nc")
    fs.add(U.Valve("HV-1", variant="saunders", normal_position="closed")).pin(x=100, y=100)
    assert ">NC</text>" in fs.to_svg()


def test_the_device_class_draws_the_actuator_too():
    """``ControlValve()`` with no variant at all is the shortest way to type a
    control valve, and it is the same drawing."""
    assert devices.ControlValve("CV-1").variant == "control"
    assert (
        devices.ControlValve("CV-2", variant="butterfly", actuator="diaphragm").variant
        == "butterfly_pneumatic"
    )


# --- the retired spelling ----------------------------------------------------


def test_the_medium_is_no_longer_a_kind_of_valve():
    with pytest.warns(DeprecationWarning, match=r"Valve\(variant='pneumatic'\)"):
        valve = U.Valve("CV-1", variant="pneumatic")
    assert valve.variant == "control", "and it still draws, for one release"


def test_the_retired_spelling_reports_on_validate():
    """The second signal: ``DeprecationWarning`` is filtered out of most
    programs, and ``fs.validate()`` is what an author is told to run."""
    fs = Flowsheet("retired")
    with pytest.warns(DeprecationWarning):
        fs.add(U.Valve("CV-1", variant="pneumatic")).pin(x=100, y=100)
    found = [i for i in fs.validate() if i.code == CODE]
    assert len(found) == 1
    assert "use Valve(variant='control')" in found[0].message


def test_the_compound_body_name_survives_the_same_argument():
    """``butterfly_pneumatic`` names a *body* with an actuator on it, which is a
    valve you can point at on a rack, and it is the only spelling for its
    drawing. ``pneumatic`` alone named neither a body nor a duty, and by 0.1.2
    named the same drawing as ``control``."""
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        assert U.Valve("XV-1", variant="butterfly_pneumatic").variant == ("butterfly_pneumatic")


def test_the_actuator_vocabulary_is_what_can_be_drawn():
    """A name that always raises is a trap rather than an API, so the list is
    exactly the operators valves.xml ships artwork for."""
    assert set(ACTUATORS) == {a for _, a in ACTUATED}
    assert "piston" not in ACTUATORS
