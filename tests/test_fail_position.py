"""Test valve fail positions (ISA-5.1 Table 5.4.4 Method B, PIP PIC001 4.2.4.6)."""

from __future__ import annotations

import pytest

from pandid import Flowsheet, spec, units
from pandid.render.symbols import FAIL_ACTUATED, FAIL_POSITIONS, fail_marking
from pandid.render.symbols import default_registry as registry
from test_normally_closed import _line

# Every valve variant the package draws, split by whether it has an actuator.
ALL_VARIANTS = sorted({v for k, v in registry._symbols if k == "valve"})
UNACTUATED = sorted(set(ALL_VARIANTS) - FAIL_ACTUATED)


# --------------------------------------------------------------------- the API


def test_a_valve_declares_no_fail_position_by_default():
    """Check that a valve declares no fail position by default."""
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
    """Check that the position can be set and cleared after construction."""
    valve = units.Valve("FV-1", variant="control")
    valve.fail = "closed"
    assert fail_marking(valve) == "FC"
    valve.fail = ""
    assert valve.fail == ""
    assert fail_marking(valve) == ""


# ----------------------------------------------------------------- the letters


@pytest.mark.parametrize("position,letters", sorted(FAIL_POSITIONS.items()))
def test_each_position_draws_its_own_letters(position, letters):
    """Check that each position draws its own letters (ISA-5.1 Table 5.4.4)."""
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
    """Check that the letters are the whole of the mark."""
    for variant in sorted(FAIL_ACTUATED):
        plain = registry.for_unit(units.Valve("FV-1", variant=variant))
        failing = registry.for_unit(units.Valve("FV-2", variant=variant, fail="closed"))
        assert failing is plain
        assert failing.ports == plain.ports
        assert (failing.width, failing.height) == (plain.width, plain.height)


# ------------------------------------------------------- valves with no actuator


@pytest.mark.parametrize("variant", UNACTUATED)
def test_a_valve_with_no_actuator_is_refused(variant):
    """Check that a valve with no actuator is refused (ISA-5.1 note 5.3.4(10))."""
    with pytest.raises(ValueError) as excinfo:
        units.Valve("HV-1", variant=variant, fail="closed")
    message = str(excinfo.value)
    assert "no actuator" in message
    assert variant in message
    assert "normal_position" in message, "the message names the neighbouring attribute"


def test_the_hand_operated_and_the_self_acting_valves_are_both_refused():
    """Check that the hand-operated and the self-acting valves are both refused."""
    for variant in ("manual", "knife", "regulator", "relief", "psv"):
        assert variant not in FAIL_ACTUATED
        with pytest.raises(ValueError, match="no actuator"):
            units.Valve("HV-1", variant=variant, fail="open")


@pytest.mark.parametrize("variant", sorted(FAIL_ACTUATED))
def test_every_actuated_variant_takes_one(variant):
    assert units.Valve("FV-1", variant=variant, fail="last").fail == "last"


def test_a_valve_retyped_after_it_declared_one_stops_the_sheet():
    """Check that a valve retyped after it declared one stops the sheet."""
    valve = units.Valve("FV-1", variant="control", fail="closed")
    valve.variant = "gate"
    with pytest.raises(ValueError, match="no actuator"):
        fail_marking(valve)


# ------------------------------------------------- composing with normal_position


def test_the_two_positions_are_independent():
    """Check that the two positions are independent."""
    valve = units.Valve("FV-1", variant="control", fail="closed")
    assert valve.normal_position == "open", "the default, not a consequence of failing shut"
    assert units.Valve("HV-1", variant="gate", normal_position="closed").fail == ""


def test_a_darkened_valve_can_also_say_where_it_fails():
    """Check that a darkened valve can also say where it fails."""
    valve = units.Valve("XV-1", variant="solenoid", normal_position="closed", fail="open")
    svg = _line(valve)
    assert 'fill="#111"' in svg, "the darkened body states the normal position"
    assert ">FO</text>" in svg, "and the letters state the fail position"


def test_the_nc_letters_and_the_fail_letters_do_not_collide():
    """Check that the NC letters and the fail letters do not collide."""
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
    """Check that the letters go below a valve on a horizontal run (PIP PIC001 4.2.4.6(1))."""
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
    """Check that the letters go to the right of a valve on a riser (PIP PIC001 4.2.4.6(1))."""
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
    """Check that the letters step past a tag already on that side."""
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
    """Check that the letters step past a tag on the riser side too."""
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


def test_the_letters_step_off_an_impulse_line_leaving_the_same_face():
    """Check that the letters step off an impulse line leaving the same face."""
    from pandid.portgeom import unit_box
    from pandid.layout.conflicts import boxes_overlap
    from pandid.render.svg import SvgRenderer, _ink, _unit_label_box

    fs = Flowsheet("a trip square below a failing valve")
    feed = fs.add(units.Feed("FEED"))
    valve = fs.add(units.Valve("XV-601", variant="solenoid", fail="closed"))
    product = fs.add(units.Product("PROD"))
    fs.connect(feed.outlet, valve.inlet)
    fs.connect(valve.outlet, product.inlet)
    fs.add_instrument("Z", 1, acting_on=valve, face="S", offset=26, variant="sis")
    fs.layout()
    svg = fs.to_svg()

    assert ">FC</text>" in svg, "the mark is drawn"
    ink = _ink(fs, "vertical")
    taps = [line for line in ink if line.kind == "tap"]
    assert len(taps) == 1, "and the square is joined to the valve by one line"

    frame = valve.frame
    symbols = [(u, unit_box(u, u.frame)) for u in fs.units if u.frame is not None]
    plate = _unit_label_box(
        SvgRenderer()._fail_label_item(
            valve, frame, frame.x, frame.y, frame.w, frame.h, "FC", None, ink, symbols
        )
    )
    assert plate is not None
    assert not boxes_overlap(plate, taps[0].box), "and the plate is clear of it"
    assert plate[1] > frame.y + frame.h, "still below the valve"
    assert plate[0] < frame.x + frame.w, "and still lying against its body"


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
    """Check that both positions round trip together."""
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
    """Check that only a valve takes a fail position in a spec."""
    with pytest.raises(spec.SpecError, match="only a Valve takes 'fail'"):
        Flowsheet.from_dict(
            {
                "name": "bad",
                "units": [
                    {"kind": "Fitting", "name": "SB-1", "variant": "blind", "fail": "closed"}
                ],
            }
        )
