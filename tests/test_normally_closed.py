"""Test normally closed valves (PIP PIC001 4.2.2.7, ISO 15519-1 §11.4.5) and spectacle blinds."""

from __future__ import annotations

import re
from dataclasses import fields, replace

import pytest

from pandid import Flowsheet, spec, units
from pandid.render.symbols import (
    NC_DARKENS,
    NC_FORBIDDEN,
    Overlay,
    PortSeries,
    Symbol,
    closed_marking,
    darkened,
)
from pandid.render.symbols import default_registry as registry

BODY_FILL = 'fill="#111"'
#: What that body carries before it is darkened, and what a bored disc keeps.
PAPER_FILL = 'fill="white"'


def _line(*valves):
    """Build a feed -> valves -> product run, laid out and rendered."""
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
    """Check that the position defaults to open and open is not marked."""
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
    """Check that the position can be set after construction."""
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
    """Check that the two are separate definitions on one sheet."""
    svg = _line(
        units.Valve("HV-1", variant="gate", normal_position="closed"),
        units.Valve("HV-2", variant="gate"),
    )
    assert svg.count('<symbol id="sym_valve_gate_nc"') == 1
    assert svg.count('<symbol id="sym_valve_gate"') == 1
    assert svg.count('href="#sym_valve_gate_nc"') == 1
    assert svg.count('href="#sym_valve_gate"') == 1


def test_darkening_leaves_the_nozzles_exactly_where_they_were():
    """Check that darkening leaves the nozzles exactly where they were."""
    for variant in sorted(NC_DARKENS):
        plain = registry.for_unit(units.Valve("HV-1", variant=variant))
        closed = registry.for_unit(units.Valve("HV-1", variant=variant, normal_position="closed"))
        assert (closed.width, closed.height) == (plain.width, plain.height)
        assert closed.ports == plain.ports
        assert closed.port_faces == plain.port_faces
        assert closed.stretchable == plain.stretchable


def test_darkening_keeps_every_field_but_the_artwork_the_id_and_the_fill() -> None:
    """Check that darkening keeps every field but the artwork, the id and the draw.io fill."""
    plain = replace(
        registry.get("valve", "gate"),
        faceless_ports=frozenset({"actuator"}),
        port_series=(PortSeries("drain_", "S"),),
        bands={"S": (2.0, 20.0)},
        family_faces={"inlet": {"S": (10.0, registry.get("valve", "gate").height)}},
        rim=((0.0, 0.0), (1.0, 0.0), (1.0, 1.0)),
        label_pos="center",
        id_suffix="_x",
        stretchable=False,
        bare_run=True,
        gravity_fixed=True,
        directional=True,
        drawio_flip_h=True,
        drawio_body_shape="mxgraph.pid.valves.valve",
        overlays=(Overlay(26, "bracket", 0.1, 0.2, 0.2, 0.1),),
        iso_reg="X8063",
    )
    closed = darkened(plain)
    assert (closed.id_suffix, closed.drawio_fill) == ("_x_nc", "#111")
    blank = Symbol(svg="", width=1.0, height=1.0)
    for f in fields(Symbol):
        if f.name not in {"svg", "id_suffix", "drawio_fill"}:
            assert getattr(plain, f.name) != getattr(blank, f.name), f"set {f.name} above"
            assert getattr(closed, f.name) == getattr(plain, f.name), f.name


def test_a_darkened_globe_is_not_confusable_with_an_ordinary_one():
    """Check that a darkened globe is not confusable with an ordinary one."""
    globe = registry.get("valve", "globe")
    closed = registry.for_unit(units.Valve("HV-1", variant="globe", normal_position="closed"))
    # The globe's seat is one filled element; the darkened body fills the outline too.
    assert globe.svg.count(BODY_FILL) == 1
    assert PAPER_FILL in globe.svg
    assert closed.svg.count(BODY_FILL) == 2
    assert closed.svg.count(PAPER_FILL) == globe.svg.count(PAPER_FILL) - 1


# ----------------------------------------------------- control / relief valves


@pytest.mark.parametrize("variant", sorted(NC_FORBIDDEN))
def test_a_control_or_relief_valve_refuses_the_mark(variant):
    """Check that a control or relief valve refuses the mark (PIP PIC001 4.2.2.10)."""
    with pytest.raises(ValueError) as excinfo:
        units.Valve("FV-1", variant=variant, normal_position="closed")
    message = str(excinfo.value)
    assert "4.2.2.10" in message, "the message names the clause it is enforcing"
    assert variant in message


def test_a_control_valve_may_still_be_declared_open():
    """Check that a control valve may still be declared open."""
    valve = units.Valve("FV-1", actuator="diaphragm", normal_position="open")
    assert valve.normal_position == "open"


# ------------------------------------------------------- the NC text fallback


@pytest.mark.parametrize("variant", ["butterfly", "check", "knife", "saunders"])
def test_a_body_that_cannot_be_darkened_says_so_in_letters(variant):
    """Check that a body that cannot be darkened says so in letters (ISO 15519-1 §11.4.5)."""
    assert variant not in NC_DARKENS
    valve = units.Valve("HV-1", variant=variant, normal_position="closed")
    assert closed_marking(valve) == "NC"
    svg = _line(valve)
    assert BODY_FILL not in svg
    assert ">NC</text>" in svg


def test_the_letters_go_above_the_valve_and_to_the_right():
    """Check that the letters go above the valve and to the right (ISO 15519-1 §11.4.5)."""
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
    """Check that the letters step past a tag already in that corner."""
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
    """Return every disc the symbol draws: centre height in symbol space -> its fill."""
    scale = float(re.search(r"scale\(([\d.]+)\)", sym.svg).group(1))
    return {
        round(float(cy) * scale, 1): fill
        for cy, fill in re.findall(r'<ellipse[^>]*cy="([\d.]+)"[^>]*fill="([^"]+)"', sym.svg)
    }


def test_a_blind_carries_the_same_attribute_a_valve_does():
    """Check that a blind carries the same attribute a valve does."""
    blind = units.Fitting("SB-1", variant="blind")
    assert blind.normal_position == "open"
    assert blind.NORMAL_POSITIONS == units.Valve.NORMAL_POSITIONS
    assert isinstance(blind, units.Unit)
    with pytest.raises(ValueError, match="normal_position is 'open' or 'closed'"):
        units.Fitting("SB-1", variant="blind", normal_position="shut")


def test_the_two_states_are_two_stencils_and_not_a_mark():
    """Check that the two states are two stencils and not a mark."""
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
    """Check that the disc in the line is bored when open and solid when closed."""
    open_blind = registry.for_unit(units.Fitting("SB-1", variant="blind"))
    shut = registry.for_unit(units.Fitting("SB-2", variant="blind", normal_position="closed"))
    line = open_blind.ports["inlet"][1]
    assert open_blind.ports["outlet"][1] == line, "both faces are on the one disc"
    for sym, in_line, parked in ((open_blind, "white", "#111"), (shut, "#111", "white")):
        discs = _discs(sym)
        assert len(discs) == 2, "a figure-8 is two discs"
        assert discs.pop(line) == in_line
        assert set(discs.values()) == {parked}


def test_a_closed_blind_renders_as_its_own_definition():
    svg = _line(units.Fitting("SB-1", variant="blind", normal_position="closed"))
    assert 'href="#sym_fitting_blind_closed"' in svg
    assert 'href="#sym_fitting_blind"' not in svg
    assert ">NC</text>" not in svg


def test_the_two_blinds_are_separate_definitions_on_one_sheet():
    svg = _line(
        units.Fitting("SB-1", variant="blind", normal_position="closed"),
        units.Fitting("SB-2", variant="blind"),
    )
    assert svg.count('<symbol id="sym_fitting_blind_closed"') == 1
    assert svg.count('<symbol id="sym_fitting_blind"') == 1


@pytest.mark.parametrize("variant", ["default", "strainer", "venturi", "spool"])
def test_a_fitting_drawn_one_way_has_no_position_to_state(variant):
    """Check that a fitting drawn one way has no position to state."""
    with pytest.raises(ValueError) as excinfo:
        units.Fitting("ST-1", variant=variant, normal_position="closed")
    assert "blind" in str(excinfo.value), "the message names the fittings that do"
    assert units.Fitting("ST-1", variant=variant, normal_position="open").normal_position == "open"


def test_a_blind_retyped_after_it_was_closed_stops_the_sheet():
    """Check that a blind retyped after it was closed stops the sheet."""
    blind = units.Fitting("SB-1", variant="blind", normal_position="closed")
    blind.variant = "strainer"
    with pytest.raises(ValueError, match="drawn one way"):
        registry.for_unit(blind)


def test_a_blanked_blind_is_not_confusable_with_a_darkened_valve():
    """Check that a blanked blind is not confusable with a darkened valve."""
    shut_valve = registry.for_unit(units.Valve("HV-1", variant="gate", normal_position="closed"))
    shut_blind = registry.for_unit(units.Fitting("SB-1", variant="blind", normal_position="closed"))
    # The valve's ink is a filled body path; the blind draws no filled path.
    assert re.search(r'<path[^>]*fill="#111"', shut_valve.svg)
    assert not re.search(r'<path[^>]*fill="#111"', shut_blind.svg)
    assert shut_valve.width > shut_valve.height
    assert shut_blind.height > shut_blind.width
    # The blind's solid disc covers under half its box; the darkened valve fills its box.
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
    """Check that a blind position round trips through a spec."""
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


def test_a_spec_may_not_close_a_control_valve():
    with pytest.raises(spec.SpecError, match="4.2.2.10"):
        Flowsheet.from_dict(
            {
                "name": "bad",
                "units": [
                    {
                        "kind": "Valve",
                        "name": "FV-1",
                        "actuator": "diaphragm",
                        "normal_position": "closed",
                    }
                ],
            }
        )
