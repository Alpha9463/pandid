"""Normally closed valves: PIP PIC001 4.2.2.7's darkened body, and 4.2.2.8's
``NC`` abbreviation for a body that cannot carry it.

Not an ISA-5.1 convention -- ISA-5.1 says nothing about valve fill -- so the
drawn behaviour is pinned here rather than assumed from any standard the rest
of the package follows.
"""

from __future__ import annotations

import pytest

from pandid import Flowsheet, spec, units
from pandid.render.symbols import NC_DARKENS, NC_FORBIDDEN, closed_marking
from pandid.render.symbols import default_registry as registry

BODY_FILL = 'fill="#111"'


def _line(*valves):
    """A feed -> valves -> product run, laid out and rendered."""
    fs = Flowsheet("normally closed")
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


def test_the_position_defaults_to_open_and_open_is_not_marked():
    """The convention is one-sided: a normally open valve is not marked at all,
    so declaring it must draw exactly what leaving it out draws."""
    plain = units.Valve("HV-1", variant="gate")
    stated = units.Valve("HV-2", variant="gate", normal_position="open")
    assert plain.normal_position == "open"
    assert registry.for_unit(stated) is registry.for_unit(plain)
    assert BODY_FILL not in registry.for_unit(stated).svg


def test_a_position_that_is_not_a_position_is_refused_by_name():
    with pytest.raises(ValueError, match="normal_position is 'open' or 'closed'"):
        units.Valve("HV-1", normal_position="shut")
    valve = units.Valve("HV-1")
    with pytest.raises(ValueError, match="normal_position"):
        valve.normal_position = True  # a bool is not one of the two names


def test_the_position_can_be_set_after_construction():
    """Same validation either way: the setter is where the rule lives, and the
    constructor goes through it."""
    valve = units.Valve("HV-1", variant="gate")
    valve.normal_position = "closed"
    assert BODY_FILL in registry.for_unit(valve).svg
    valve.normal_position = "open"
    assert BODY_FILL not in registry.for_unit(valve).svg


# ------------------------------------------------------------------- the fill


def test_a_normally_closed_valve_renders_with_a_darkened_body():
    svg = _line(units.Valve("HV-1", variant="gate", normal_position="closed"))
    assert "sym_valve_gate_nc" in svg
    assert BODY_FILL in svg


def test_an_ordinary_valve_renders_with_an_open_body():
    svg = _line(units.Valve("HV-1", variant="gate"))
    assert "sym_valve_gate_nc" not in svg
    assert BODY_FILL not in svg


def test_the_two_are_separate_definitions_on_one_sheet():
    """A darkened body is a different drawing, so it needs a ``<defs>`` entry of
    its own; sharing one would draw both valves the same way."""
    svg = _line(
        units.Valve("HV-1", variant="gate", normal_position="closed"),
        units.Valve("HV-2", variant="gate"),
    )
    assert svg.count('<symbol id="sym_valve_gate_nc"') == 1
    assert svg.count('<symbol id="sym_valve_gate"') == 1
    assert svg.count('href="#sym_valve_gate_nc"') == 1
    assert svg.count('href="#sym_valve_gate"') == 1


def test_darkening_leaves_the_nozzles_exactly_where_they_were():
    """The fill is a statement about the valve's position, not about its size or
    its connections: a line already drawn must not move because the valve was
    declared closed."""
    for variant in sorted(NC_DARKENS):
        plain = registry.for_unit(units.Valve("HV-1", variant=variant))
        closed = registry.for_unit(units.Valve("HV-1", variant=variant, normal_position="closed"))
        assert (closed.width, closed.height) == (plain.width, plain.height)
        assert closed.ports == plain.ports
        assert closed.port_faces == plain.port_faces
        assert closed.stretchable == plain.stretchable


def test_a_darkened_globe_is_not_confusable_with_an_ordinary_one():
    """The globe's seat is a device marker and the fill is a position marker,
    and the two must not be read for each other. They are held apart by the
    triangles, which are the largest part of the symbol: white on a globe in
    any position, black once the body is darkened."""
    globe = registry.get("valve", "globe")
    closed = registry.for_unit(units.Valve("HV-1", variant="globe", normal_position="closed"))
    # The seat is one filled element inside an outline drawn fill="none"; the
    # darkened body is that outline itself filled.
    assert globe.svg.count(BODY_FILL) == 1
    assert 'fill="none"' in globe.svg
    assert closed.svg.count(BODY_FILL) == 2
    assert closed.svg.count('fill="none"') == globe.svg.count('fill="none"') - 1


# ----------------------------------------------------- control / relief valves


@pytest.mark.parametrize("variant", sorted(NC_FORBIDDEN))
def test_a_control_or_relief_valve_refuses_the_mark(variant):
    """PIP PIC001 4.2.2.10: "Control valves or relief valves shall not be shown
    as NC." A darkened control valve on an issued sheet reads as a block valve
    someone has closed, so this is a drafting error and is refused rather than
    warned about."""
    with pytest.raises(ValueError) as excinfo:
        units.Valve("FV-1", variant=variant, normal_position="closed")
    message = str(excinfo.value)
    assert "4.2.2.10" in message, "the message names the clause it is enforcing"
    assert variant in message


def test_a_control_valve_may_still_be_declared_open():
    """The prohibition is on showing one *closed*; a control valve is a valve
    like any other otherwise."""
    valve = units.Valve("FV-1", variant="control", normal_position="open")
    assert valve.normal_position == "open"


# ------------------------------------------------------- the NC text fallback


@pytest.mark.parametrize("variant", ["butterfly", "butterfly_pneumatic", "check", "knife"])
def test_a_body_that_cannot_be_darkened_says_so_in_letters(variant):
    """PIP PIC001 4.2.2.8. The failure this guards against is silence: a valve
    declared closed whose symbol cannot carry the fill would otherwise draw
    exactly the open valve and say nothing at all."""
    assert variant not in NC_DARKENS
    valve = units.Valve("HV-1", variant=variant, normal_position="closed")
    assert closed_marking(valve) == "NC"
    svg = _line(valve)
    assert BODY_FILL not in svg
    assert ">NC</text>" in svg


def test_the_letters_go_below_a_horizontal_valve_and_right_of_a_vertical_one():
    """PIP PIC001 4.2.2.8 places the abbreviation directly below the valve on a
    horizontal line and to the right of it on a vertical one. An inline symbol
    is drawn along its run, so the quarter turn is which line it is in."""
    from pandid.render.svg import SvgRenderer

    flat = units.Valve("HV-1", variant="butterfly", normal_position="closed")
    upright = units.Valve("HV-2", variant="butterfly", normal_position="closed")
    fs = Flowsheet("nc placement")
    feed = fs.add(units.Feed("FEED"))
    fs.add(flat)
    fs.add(upright).pin(orientation=90)
    product = fs.add(units.Product("PROD"))
    fs.connect(feed.outlet, flat.inlet)
    fs.connect(flat.outlet, upright.inlet)
    fs.connect(upright.outlet, product.inlet)
    fs.layout()

    renderer = SvgRenderer()
    for valve, side in ((flat, "bottom"), (upright, "right")):
        frame = valve.frame
        item = renderer._nc_label_item(
            valve, frame, frame.x, frame.y, frame.w, frame.h, int(frame.orientation or 0)
        )
        assert item[4] == side
        lx, ly = item[0], item[1]
        if side == "bottom":
            assert ly > frame.y + frame.h
            assert abs(lx - (frame.x + frame.w / 2)) < 1e-9
        else:
            assert lx > frame.x + frame.w
            assert abs(ly - (frame.y + frame.h / 2)) < 1e-9


def test_the_letters_step_past_a_tag_already_on_that_side():
    """Both are drawn on opaque halos in one final pass, so an abbreviation
    landing on the tag would simply erase it."""
    from pandid.render.svg import SvgRenderer

    valve = units.Valve("HV-1", variant="butterfly", normal_position="closed", label_pos="bottom")
    fs = Flowsheet("nc under a tag")
    feed = fs.add(units.Feed("FEED"))
    fs.add(valve)
    product = fs.add(units.Product("PROD"))
    fs.connect(feed.outlet, valve.inlet)
    fs.connect(valve.outlet, product.inlet)
    fs.layout()

    renderer = SvgRenderer()
    frame = valve.frame
    tag = renderer._unit_label_item(valve, frame, frame.x, frame.y, frame.w, frame.h, "HV-1")
    nc = renderer._nc_label_item(valve, frame, frame.x, frame.y, frame.w, frame.h, 0)
    assert nc[1] > tag[1], "the abbreviation clears the tag it would have landed on"


# ------------------------------------------------------------- the spec layer


def test_the_position_round_trips_through_a_spec():
    fs = Flowsheet("round trip")
    fs.add(units.Valve("HV-1", variant="gate", normal_position="closed"))
    fs.add(units.Valve("HV-2", variant="gate"))

    written = spec.to_dict(fs)
    entries = {u["name"]: u for u in written["units"]}
    assert entries["HV-1"]["normal_position"] == "closed"
    assert "normal_position" not in entries["HV-2"], "open is the default, not an entry"

    rebuilt = Flowsheet.from_dict(written)
    positions = {u.name: u.normal_position for u in rebuilt.units}
    assert positions == {"HV-1": "closed", "HV-2": "open"}
    assert spec.to_dict(rebuilt) == written


def test_a_spec_position_that_is_not_one_names_the_entry():
    with pytest.raises(spec.SpecError, match=r"units\[0\] 'HV-1'"):
        Flowsheet.from_dict(
            {"name": "bad", "units": [{"kind": "Valve", "name": "HV-1", "normal_position": "shut"}]}
        )


def test_only_a_valve_takes_a_normal_position_in_a_spec():
    with pytest.raises(spec.SpecError, match="only a Valve takes 'normal_position'"):
        Flowsheet.from_dict(
            {
                "name": "bad",
                "units": [{"kind": "Pump", "name": "P-101", "normal_position": "closed"}],
            }
        )


def test_a_spec_may_not_close_a_control_valve():
    with pytest.raises(spec.SpecError, match="4.2.2.10"):
        Flowsheet.from_dict(
            {
                "name": "bad",
                "units": [
                    {
                        "kind": "Valve",
                        "name": "FV-1",
                        "variant": "control",
                        "normal_position": "closed",
                    }
                ],
            }
        )
