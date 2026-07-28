"""Devices declared in a normal position, and what each one draws for it.

Normally closed valves: PIP PIC001 4.2.2.7's darkened body, and ISO 15519-1
§11.4.5's ``NC`` abbreviation for a body that cannot carry it. Two sources
because only one standard offers each -- no ISO or ISA document fills a valve
body, and ISO 15519-1 §11.4.5 is the clause that rules on the letters -- so the
drawn behaviour is pinned here rather than assumed from any one of them.

Spectacle blinds: the same ``normal_position``, drawn a different way. A blind
is two discs and the sheet says which is in the line by filling it, so the two
states are two *shapes* the stencil set already draws, not a mark applied to
one of them.
"""

from __future__ import annotations

import re

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
    """ISO 15519-1 §11.4.5. The failure this guards against is silence: a valve
    declared closed whose symbol cannot carry the fill would otherwise draw
    exactly the open valve and say nothing at all."""
    assert variant not in NC_DARKENS
    valve = units.Valve("HV-1", variant=variant, normal_position="closed")
    assert closed_marking(valve) == "NC"
    svg = _line(valve)
    assert BODY_FILL not in svg
    assert ">NC</text>" in svg


def test_the_letters_go_above_the_valve_and_to_the_right():
    """ISO 15519-1 §11.4.5 puts the abbreviation "above the symbol and to the
    right", as Figure 28 draws it. The corner is fixed rather than chosen from
    the valve's quarter turn, so a valve in a vertical run is marked in the same
    corner as one in a horizontal run and a reader scans a sheet for one thing.
    """
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
    for valve in (flat, upright):
        frame = valve.frame
        lx, ly, anchor, _, lpos, text = renderer._nc_label_item(
            valve, frame, frame.x, frame.y, frame.w, frame.h
        )
        assert (lpos, text, anchor) == ("top_right", "NC", "start")
        assert ly < frame.y, "above the symbol"
        assert lx >= frame.x + frame.w, "and to the right"


def test_the_letters_step_past_a_tag_already_in_that_corner():
    """Both are drawn on opaque halos in one final pass, so an abbreviation
    landing on the tag would simply erase it. A valve's tag sits centred above
    it by default, and a valve body is narrower than its own tag, so the two
    reach for the same corner on an ordinary sheet rather than a contrived one.
    """
    from pandid.render.svg import SvgRenderer, _unit_label_box

    valve = units.Valve("HV-101", variant="butterfly", normal_position="closed")
    fs = Flowsheet("nc beside a tag")
    feed = fs.add(units.Feed("FEED"))
    fs.add(valve)
    product = fs.add(units.Product("PROD"))
    fs.connect(feed.outlet, valve.inlet)
    fs.connect(valve.outlet, product.inlet)
    fs.layout()

    renderer = SvgRenderer()
    frame = valve.frame
    args = (valve, frame, frame.x, frame.y, frame.w, frame.h)
    tag = _unit_label_box(renderer._unit_label_item(*args, "HV-101"))
    assert tag[2] > frame.x + frame.w, "the tag really does reach into that corner"
    nc = _unit_label_box(renderer._nc_label_item(*args))
    assert nc[0] >= tag[2], "the abbreviation clears the tag it would have landed on"
    assert nc[1] < frame.y, "and is still above the valve"


# ------------------------------------------------------- the spectacle blind


def _discs(sym):
    """Every disc the symbol draws: centre height in symbol space -> its fill.

    The artwork is drawn in the stencil's own units inside one uniform
    ``scale()``, so the factor is undone here to compare a disc's centre with a
    port, which is authored in the symbol's coordinates.
    """
    scale = float(re.search(r"scale\(([\d.]+)\)", sym.svg).group(1))
    return {
        round(float(cy) * scale, 1): fill
        for cy, fill in re.findall(r'<ellipse[^>]*cy="([\d.]+)"[^>]*fill="([^"]+)"', sym.svg)
    }


def test_a_blind_carries_the_same_attribute_a_valve_does():
    """One vocabulary, held in one place: the shared base is what keeps the
    valve's names and the blind's from drifting into two spellings of one idea."""
    blind = units.Fitting("SB-1", variant="blind")
    assert blind.normal_position == "open"
    assert blind.NORMAL_POSITIONS == units.Valve.NORMAL_POSITIONS
    assert isinstance(blind, units.Unit)
    with pytest.raises(ValueError, match="normal_position is 'open' or 'closed'"):
        units.Fitting("SB-1", variant="blind", normal_position="shut")


def test_the_two_states_are_two_stencils_and_not_a_mark():
    """The blind's position is *which shape*, not something added to one. Both
    are drawn upstream, so the closed state is a registered symbol rather than a
    derived one -- and everything except the ink has to be identical, or
    declaring the position would move a line already drawn."""
    open_blind = registry.for_unit(units.Fitting("SB-1", variant="blind"))
    shut = registry.for_unit(units.Fitting("SB-2", variant="blind", normal_position="closed"))
    assert open_blind is registry.get("fitting", "blind")
    assert shut is registry.closed_symbol("fitting", "blind")
    assert shut.svg != open_blind.svg
    assert (shut.width, shut.height) == (open_blind.width, open_blind.height)
    assert shut.ports == open_blind.ports
    assert shut.port_faces == open_blind.port_faces
    assert shut.stretchable == open_blind.stretchable
    assert closed_marking(units.Fitting("SB-2", variant="blind", normal_position="closed")) == (
        "stencil"
    )


def test_the_disc_in_the_line_is_bored_when_open_and_solid_when_closed():
    """The whole of what the symbol says. The run enters at the inlet's height,
    so the disc centred there is the one in the line: a ring lets the line
    through, a solid plate blanks it, and the other disc is parked off the run
    carrying the opposite fill."""
    open_blind = registry.for_unit(units.Fitting("SB-1", variant="blind"))
    shut = registry.for_unit(units.Fitting("SB-2", variant="blind", normal_position="closed"))
    line = open_blind.ports["inlet"][1]
    assert open_blind.ports["outlet"][1] == line, "both faces are on the one disc"
    for sym, in_line, parked in ((open_blind, "none", "#111"), (shut, "#111", "none")):
        discs = _discs(sym)
        assert len(discs) == 2, "a figure-8 is two discs"
        assert discs.pop(line) == in_line
        assert set(discs.values()) == {parked}


def test_a_closed_blind_renders_as_its_own_definition():
    svg = _line(units.Fitting("SB-1", variant="blind", normal_position="closed"))
    assert 'href="#sym_fitting_blind_closed"' in svg
    assert 'href="#sym_fitting_blind"' not in svg


def test_the_two_blinds_are_separate_definitions_on_one_sheet():
    svg = _line(
        units.Fitting("SB-1", variant="blind", normal_position="closed"),
        units.Fitting("SB-2", variant="blind"),
    )
    assert svg.count('<symbol id="sym_fitting_blind_closed"') == 1
    assert svg.count('<symbol id="sym_fitting_blind"') == 1


def test_a_closed_blind_is_not_lettered_nc():
    """PIP PIC001's abbreviation is the *valve* fallback, for a body that cannot
    carry a fill. A blind's position is drawn, so lettering it would say the
    same thing twice -- and the letters are what a reader looks for on a valve."""
    svg = _line(units.Fitting("SB-1", variant="blind", normal_position="closed"))
    assert ">NC</text>" not in svg


@pytest.mark.parametrize("variant", ["default", "strainer", "venturi", "spool"])
def test_a_fitting_drawn_one_way_has_no_position_to_state(variant):
    """A strainer is a strainer whatever the plant is doing. Declaring one
    closed would set an attribute nothing on the sheet draws, which is the
    silence that makes a wrong drawing plausible."""
    with pytest.raises(ValueError) as excinfo:
        units.Fitting("ST-1", variant=variant, normal_position="closed")
    assert "blind" in str(excinfo.value), "the message names the fittings that do"
    assert units.Fitting("ST-1", variant=variant, normal_position="open").normal_position == "open"


def test_a_blind_retyped_after_it_was_closed_stops_the_sheet():
    """The refusal is at construction, and ``variant`` is a plain attribute, so
    it can still be assigned past it. Drawing the open symbol then would be the
    silent failure this whole feature exists to avoid: a sheet issued showing a
    line open when the model says it is blanked."""
    blind = units.Fitting("SB-1", variant="blind", normal_position="closed")
    blind.variant = "strainer"
    with pytest.raises(ValueError, match="drawn one way"):
        registry.for_unit(blind)


def test_a_blanked_blind_is_not_confusable_with_a_darkened_valve():
    """Both say "closed" with ink, so the two must not be read for each other.
    A valve fills its whole body, which is a bowtie lying along the run; a blind
    fills one small disc, straddling the run with its companion and its handle
    clear of it. Different shape, different axis, different share of the box."""
    shut_valve = registry.for_unit(units.Valve("HV-1", variant="gate", normal_position="closed"))
    shut_blind = registry.for_unit(units.Fitting("SB-1", variant="blind", normal_position="closed"))
    # The valve's ink is its body: a filled <path>, running the length of a box
    # wider than it is tall. The blind draws no filled path at all.
    assert re.search(r'<path[^>]*fill="#111"', shut_valve.svg)
    assert not re.search(r'<path[^>]*fill="#111"', shut_blind.svg)
    assert shut_valve.width > shut_valve.height
    assert shut_blind.height > shut_blind.width
    # ...and the blind's solid disc covers a small part of its box, where the
    # valve's darkened body is the box. _FEATURE_AREA in the invariant suite is
    # the same 0.5 boundary, from the other side.
    solid = float(re.search(r'<ellipse[^>]*rx="([\d.]+)"[^>]*fill="#111"', shut_blind.svg).group(1))
    scale = float(re.search(r"scale\(([\d.]+)\)", shut_blind.svg).group(1))
    covered = (2 * solid * scale) ** 2 / (shut_blind.width * shut_blind.height)
    assert covered < 0.5


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


def test_a_blind_position_round_trips_through_a_spec():
    """Both directions, and both states: the position is the only thing that
    tells the two drawings apart, so a spec that loses it loses the drawing."""
    fs = Flowsheet("round trip")
    fs.add(units.Fitting("SB-1", variant="blind", normal_position="closed"))
    fs.add(units.Fitting("SB-2", variant="blind"))
    fs.add(units.Fitting("ST-1", variant="strainer"))

    written = spec.to_dict(fs)
    entries = {u["name"]: u for u in written["units"]}
    assert entries["SB-1"]["normal_position"] == "closed"
    assert "normal_position" not in entries["SB-2"], "open is the default, not an entry"
    assert "normal_position" not in entries["ST-1"]

    rebuilt = Flowsheet.from_dict(written)
    positions = {u.name: u.normal_position for u in rebuilt.units}
    assert positions == {"SB-1": "closed", "SB-2": "open", "ST-1": "open"}
    assert spec.to_dict(rebuilt) == written
    drawn = {u.name: registry.for_unit(u).symbol_id() for u in rebuilt.units}
    assert drawn["SB-1"] == "sym_fitting_blind_closed"
    assert drawn["SB-2"] == "sym_fitting_blind"


def test_a_spec_may_not_close_a_fitting_that_is_drawn_one_way():
    with pytest.raises(spec.SpecError, match="no normally closed position"):
        Flowsheet.from_dict(
            {
                "name": "bad",
                "units": [
                    {
                        "kind": "Fitting",
                        "name": "ST-1",
                        "variant": "strainer",
                        "normal_position": "closed",
                    }
                ],
            }
        )


def test_a_spec_position_that_is_not_one_names_the_entry():
    with pytest.raises(spec.SpecError, match=r"units\[0\] 'HV-1'"):
        Flowsheet.from_dict(
            {"name": "bad", "units": [{"kind": "Valve", "name": "HV-1", "normal_position": "shut"}]}
        )


def test_only_a_positioned_unit_takes_a_normal_position_in_a_spec():
    with pytest.raises(spec.SpecError, match="only a Valve or a Fitting takes 'normal_position'"):
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
