"""Where an actuated valve goes when its motive power is lost.

A different property from ``normal_position``, from a different clause, drawn in
a different place, and the pair is the easiest thing on a P&ID to run together:
normal position is where the valve sits with the plant running, fail position is
where it goes when the air or the power is lost. A valve can be normally open
and fail closed, and both marks belong on the sheet.

The letters are ANSI/ISA-5.1-2009 Table 5.4.4 Method B rather than the same
table's Method A stem arrows, because PIP PIC001 4.5.3.2 chooses between them:
"automated valve fail actions shall be shown with text (FC/FO/FL/FI) in
accordance with ISA-5.1", with the comment that "using stem arrows as outlined
in ISA-5.1 is not recommended". PIP PIC001 4.2.4.6(1) then places them, below a
valve on a horizontal run and to the right of one on a vertical run.
"""

from __future__ import annotations

import pytest

from pandid import Flowsheet, spec, units
from pandid.render.symbols import FAIL_ACTUATED, FAIL_POSITIONS, fail_marking
from pandid.render.symbols import default_registry as registry

# Every valve variant the package draws, split by whether it has an actuator.
ALL_VARIANTS = sorted({v for k, v in registry._symbols if k == "valve"})
UNACTUATED = sorted(set(ALL_VARIANTS) - FAIL_ACTUATED)


def _line(*valves):
    """A feed -> valves -> product run, laid out and rendered."""
    fs = Flowsheet("fail positions")
    feed = fs.add(units.Feed("FEED"))
    prev = feed.outlet
    for valve in valves:
        fs.add(valve)
        fs.connect(prev, valve.inlet)
        prev = valve.outlet
    product = fs.add(units.Product("PROD"))
    fs.connect(prev, product.inlet)
    fs.layout()
    return fs.to_svg()


# --------------------------------------------------------------------- the API


def test_a_valve_declares_no_fail_position_by_default():
    """Silence is the absence of a declaration, not a state. There is no
    default fail position to leave unwritten the way ``normal_position="open"``
    is left unwritten, because an unmarked valve does not fail anywhere in
    particular -- the sheet simply has not said."""
    valve = units.Valve("FV-1", variant="control")
    assert valve.fail == ""
    assert fail_marking(valve) == ""
    assert ">FC</text>" not in _line(valve)


def test_a_position_that_is_not_one_is_refused_by_name():
    with pytest.raises(ValueError) as excinfo:
        units.Valve("FV-1", variant="control", fail="shut")
    message = str(excinfo.value)
    for name in FAIL_POSITIONS:
        assert repr(name) in message, "the message lists the positions there are"
    assert "normal_position" in message, "and names the attribute it is not"


def test_the_position_can_be_set_and_cleared_after_construction():
    """Same validation either way: the setter is where the rule lives, and the
    constructor goes through it."""
    valve = units.Valve("FV-1", variant="control")
    valve.fail = "closed"
    assert fail_marking(valve) == "FC"
    valve.fail = ""
    assert valve.fail == ""
    assert fail_marking(valve) == ""


# ----------------------------------------------------------------- the letters


@pytest.mark.parametrize("position,letters", sorted(FAIL_POSITIONS.items()))
def test_each_position_draws_its_own_letters(position, letters):
    """ANSI/ISA-5.1-2009 Table 5.4.4 Method B, plus ``FI`` from ISA-5.1-1984
    §6.7, which PIP PIC001 4.5.3.2 keeps in its own list of four."""
    valve = units.Valve("FV-1", variant="control", fail=position)
    assert fail_marking(valve) == letters
    assert f">{letters}</text>" in _line(valve)


def test_the_six_letter_codes_are_the_ones_the_standards_write():
    assert FAIL_POSITIONS == {
        "open": "FO",
        "closed": "FC",
        "last": "FL",
        "drift_open": "FL/DO",
        "drift_closed": "FL/DC",
        "indeterminate": "FI",
    }


def test_the_letters_are_the_whole_of_the_mark():
    """Unlike a darkened body, a fail position changes no artwork at all, so
    declaring one can never move a line that is already drawn."""
    for variant in sorted(FAIL_ACTUATED):
        plain = registry.for_unit(units.Valve("FV-1", variant=variant))
        failing = registry.for_unit(units.Valve("FV-2", variant=variant, fail="closed"))
        assert failing is plain
        assert failing.ports == plain.ports
        assert (failing.width, failing.height) == (plain.width, plain.height)


# ------------------------------------------------------- valves with no actuator


@pytest.mark.parametrize("variant", UNACTUATED)
def test_a_valve_with_no_actuator_is_refused(variant):
    """ANSI/ISA-5.1 note 5.3.4(10) scopes the failure symbols to "all types of
    control valves and actuators". A handwheel loses no air, and a regulator or
    a relief valve is worked by the process it sits in, so there is no supply
    whose failure is the question. Declaring one would set an attribute about
    equipment the valve does not have."""
    with pytest.raises(ValueError) as excinfo:
        units.Valve("HV-1", variant=variant, fail="closed")
    message = str(excinfo.value)
    assert "no actuator" in message
    assert variant in message
    assert "normal_position" in message, "the message names the neighbouring attribute"


def test_the_hand_operated_and_the_self_acting_valves_are_both_refused():
    """Two different reasons, one refusal. ``manual`` and ``knife`` draw an
    *operator* -- a handwheel -- which is not an actuator; ``regulator``,
    ``relief`` and ``psv`` are driven by the process itself."""
    for variant in ("manual", "knife", "regulator", "relief", "psv"):
        assert variant not in FAIL_ACTUATED
        with pytest.raises(ValueError, match="no actuator"):
            units.Valve("HV-1", variant=variant, fail="open")


@pytest.mark.parametrize("variant", sorted(FAIL_ACTUATED))
def test_every_actuated_variant_takes_one(variant):
    assert units.Valve("FV-1", variant=variant, fail="last").fail == "last"


def test_a_valve_retyped_after_it_declared_one_stops_the_sheet():
    """The refusal is at construction, and ``variant`` is a plain attribute, so
    it can still be assigned past it. Drawing nothing then would be the silent
    failure: a sheet issued with a trip valve whose fail position is in the
    model and nowhere on the paper."""
    valve = units.Valve("FV-1", variant="control", fail="closed")
    valve.variant = "gate"
    with pytest.raises(ValueError, match="no actuator"):
        fail_marking(valve)


# ------------------------------------------------- composing with normal_position


def test_the_two_positions_are_independent():
    """A control valve may say where it fails without any claim about a normal
    position, and nothing infers one from the other."""
    valve = units.Valve("FV-1", variant="control", fail="closed")
    assert valve.normal_position == "open", "the default, not a consequence of failing shut"
    assert units.Valve("HV-1", variant="gate", normal_position="closed").fail == ""


def test_a_darkened_valve_can_also_say_where_it_fails():
    """A solenoid held shut in service and driven open on a trip. The body is
    darkened for the normal position (PIP PIC001 4.2.2.7) and lettered for the
    fail position (ISA-5.1 Table 5.4.4): two marks, two clauses, one valve."""
    valve = units.Valve("XV-1", variant="solenoid", normal_position="closed", fail="open")
    svg = _line(valve)
    assert 'fill="#111"' in svg, "the darkened body states the normal position"
    assert ">FO</text>" in svg, "and the letters state the fail position"


def test_the_nc_letters_and_the_fail_letters_do_not_collide():
    """The hardest case: both marks are *letters* on one valve, because a
    butterfly disc cannot carry the fill. They go in two places that cannot
    overlap -- ``NC`` above and to the right (ISO 15519-1 §11.4.5), the fail
    letters below (PIP PIC001 4.2.4.6) -- and the boxes are checked rather than
    assumed, since both are drawn on opaque halos in one pass and the second
    one down would erase the first."""
    from pandid.render.svg import SvgRenderer, _unit_label_box

    valve = units.Valve(
        "XV-101", variant="butterfly_pneumatic", normal_position="closed", fail="closed"
    )
    svg = _line(valve)
    assert ">NC</text>" in svg
    assert ">FC</text>" in svg

    renderer = SvgRenderer()
    frame = valve.frame
    args = (valve, frame, frame.x, frame.y, frame.w, frame.h)
    boxes = [
        _unit_label_box(renderer._unit_label_item(*args, "XV-101")),
        _unit_label_box(renderer._nc_label_item(*args)),
        _unit_label_box(renderer._fail_label_item(*args, "FC")),
    ]
    for i, a in enumerate(boxes):
        for b in boxes[i + 1 :]:
            assert not (a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]), (
                f"{a} overlaps {b}"
            )


# --------------------------------------------------------------- where they sit


def test_the_letters_go_below_a_valve_on_a_horizontal_run():
    """PIP PIC001 4.2.4.6(1): "directly below the control valve in horizontal
    lines"."""
    from pandid.render.svg import SvgRenderer

    valve = units.Valve("FV-1", variant="control", fail="closed")
    _line(valve)
    frame = valve.frame
    lx, ly, anchor, _, lpos, text = SvgRenderer()._fail_label_item(
        valve, frame, frame.x, frame.y, frame.w, frame.h, "FC"
    )
    assert (lpos, text, anchor) == ("bottom", "FC", "middle")
    assert ly > frame.y + frame.h, "below the symbol"
    assert frame.x < lx < frame.x + frame.w, "and directly below it, not off to a side"


def test_the_letters_go_to_the_right_of_a_valve_on_a_riser():
    """PIP PIC001 4.2.4.6(1): "to the right of the control valve in vertical
    lines". Unlike the fixed ``NC`` corner, this one moves with the quarter
    turn, because it has to: the face below a valve on a riser is its outlet
    nozzle, with the line running out of it."""
    from pandid.render.svg import SvgRenderer

    flat = units.Valve("FV-1", variant="control", fail="closed")
    upright = units.Valve("FV-2", variant="control", fail="closed")
    fs = Flowsheet("fail placement")
    feed = fs.add(units.Feed("FEED"))
    fs.add(flat)
    fs.add(upright).pin(orientation=90)
    product = fs.add(units.Product("PROD"))
    fs.connect(feed.outlet, flat.inlet)
    fs.connect(flat.outlet, upright.inlet)
    fs.connect(upright.outlet, product.inlet)
    fs.layout()

    frame = upright.frame
    lx, ly, anchor, _, lpos, text = SvgRenderer()._fail_label_item(
        upright, frame, frame.x, frame.y, frame.w, frame.h, "FC"
    )
    assert (lpos, text, anchor) == ("right", "FC", "start")
    assert lx >= frame.x + frame.w, "to the right of the symbol"
    assert frame.y < ly < frame.y + frame.h, "and beside it, not under the outlet"


def test_the_letters_step_past_a_tag_already_on_that_side():
    """Both are drawn on opaque halos in one final pass, so letters landing on
    the tag would simply erase it. ``label_pos="bottom"`` is the ordinary way
    to reach this: it puts the tag on exactly the side PIP asks the letters
    for."""
    from pandid.render.svg import SvgRenderer, _unit_label_box

    valve = units.Valve("FV-101", variant="control", fail="closed", label_pos="bottom")
    _line(valve)

    renderer = SvgRenderer()
    frame = valve.frame
    args = (valve, frame, frame.x, frame.y, frame.w, frame.h)
    tag = _unit_label_box(renderer._unit_label_item(*args, "FV-101"))
    letters = _unit_label_box(renderer._fail_label_item(*args, "FC"))
    assert letters[1] >= tag[3], "the letters clear the tag they would have landed on"
    assert letters[1] > frame.y + frame.h, "and are still below the valve"


def test_the_letters_step_past_a_tag_on_the_riser_side_too():
    """The same collision on the other side. A valve on a riser wants the
    right-hand face, and that is a side the engine picks for a tag freely, so
    the step is along the axis that side runs off rather than always downwards.
    """
    from pandid.render.svg import SvgRenderer, _unit_label_box

    valve = units.Valve("FV-102", variant="control", fail="closed", label_pos="right")
    fs = Flowsheet("fail placement on a riser")
    feed = fs.add(units.Feed("FEED"))
    fs.add(valve).pin(orientation=90)
    product = fs.add(units.Product("PROD"))
    fs.connect(feed.outlet, valve.inlet)
    fs.connect(valve.outlet, product.inlet)
    fs.layout()

    renderer = SvgRenderer()
    frame = valve.frame
    args = (valve, frame, frame.x, frame.y, frame.w, frame.h)
    tag = _unit_label_box(renderer._unit_label_item(*args, "FV-102"))
    letters = _unit_label_box(renderer._fail_label_item(*args, "FC"))
    assert letters[0] >= tag[2], "the letters clear the tag they would have landed on"
    assert not (
        tag[0] < letters[2] and tag[2] > letters[0] and tag[1] < letters[3] and tag[3] > letters[1]
    )
    assert letters[0] > frame.x + frame.w, "and are still to the right of the valve"
    assert ">FC</text>" in fs.to_svg()


# ------------------------------------------------------------- the spec layer


def test_the_position_round_trips_through_a_spec():
    fs = Flowsheet("round trip")
    fs.add(units.Valve("FV-1", variant="control", fail="closed"))
    fs.add(units.Valve("FV-2", variant="butterfly", actuator="diaphragm", fail="drift_open"))
    fs.add(units.Valve("FV-3", variant="control"))

    written = spec.to_dict(fs)
    entries = {u["name"]: u for u in written["units"]}
    assert entries["FV-1"]["fail"] == "closed"
    assert entries["FV-2"]["fail"] == "drift_open"
    assert "fail" not in entries["FV-3"], "undeclared is not a value to write down"

    rebuilt = Flowsheet.from_dict(written)
    assert {u.name: u.fail for u in rebuilt.units} == {
        "FV-1": "closed",
        "FV-2": "drift_open",
        "FV-3": "",
    }
    assert spec.to_dict(rebuilt) == written


def test_both_positions_round_trip_together():
    """The pair is what a spec most easily loses, since one is written only when
    closed and the other only when declared."""
    fs = Flowsheet("round trip")
    fs.add(units.Valve("XV-1", variant="solenoid", normal_position="closed", fail="open"))

    written = spec.to_dict(fs)
    entry = written["units"][0]
    assert entry["normal_position"] == "closed"
    assert entry["fail"] == "open"

    rebuilt = Flowsheet.from_dict(written)
    valve = rebuilt.units[0]
    assert (valve.normal_position, valve.fail) == ("closed", "open")
    assert spec.to_dict(rebuilt) == written


def test_a_spec_may_not_fail_a_valve_with_no_actuator():
    with pytest.raises(spec.SpecError, match="no actuator"):
        Flowsheet.from_dict(
            {
                "name": "bad",
                "units": [{"kind": "Valve", "name": "HV-1", "variant": "gate", "fail": "closed"}],
            }
        )


def test_a_spec_position_that_is_not_one_names_the_entry():
    with pytest.raises(spec.SpecError, match=r"units\[0\] 'FV-1'"):
        Flowsheet.from_dict(
            {
                "name": "bad",
                "units": [{"kind": "Valve", "name": "FV-1", "variant": "control", "fail": "shut"}],
            }
        )


def test_only_a_valve_takes_a_fail_position_in_a_spec():
    """A blind has a position but no actuator, so ``normal_position`` is shared
    with ``Fitting`` and this is not."""
    with pytest.raises(spec.SpecError, match="only a Valve takes 'fail'"):
        Flowsheet.from_dict(
            {
                "name": "bad",
                "units": [
                    {"kind": "Fitting", "name": "SB-1", "variant": "blind", "fail": "closed"}
                ],
            }
        )
