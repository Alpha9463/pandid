"""Check the mechanical flotation cell."""

import pytest

from pandid import Blower, Feed, Flowsheet, FlotationCell, Product
from pandid.portgeom import port_faces
from pandid.render import symbols
from pandid.render.symbols import MIN_NOZZLE_PITCH, default_registry, overlay_boxes

#: The registered body, without its rotor.
BODY = default_registry.get("flotation_cell")


def _parts(unit):
    """Return the parts the unit's drawing carries."""
    return default_registry.for_unit(unit).overlays


def test_each_nozzle_leaves_by_its_own_face():
    """Check that feed, concentrate, tailings and air leave W, E, S and N."""
    unit = FlotationCell("FC-101")
    faces = {name: port_faces(unit, name)[0] for name in unit.ports}
    assert faces == {"feed": "W", "concentrate": "E", "tailings": "S", "air": "N"}


def test_the_concentrate_leaves_the_launder_and_the_tailings_the_tank():
    """Check that froth leaves outside the lip and tailings inside the tank."""
    concentrate_x, concentrate_y = BODY.ports["concentrate"]
    assert concentrate_x > symbols.FLOT_TANK_W, "the concentrate leaves the tank, not the launder"
    assert symbols._FLOT_LIP < concentrate_y <= symbols._FLOT_LAUNDER_FLOOR
    assert BODY.ports["tailings"][0] < symbols.FLOT_TANK_W


def test_the_rotor_hangs_on_the_tank_centre_line_clear_of_the_air():
    """Check that the default rotor is a turbine centred in the tank, apart from the air."""
    parts = _parts(FlotationCell("FC-101"))
    assert [(o.group, o.name) for o in parts] == [(28, "turbine")]
    ((left, top, right, bottom),) = overlay_boxes(BODY, parts)
    shaft_x = (left + right) / 2
    assert shaft_x == pytest.approx(symbols.FLOT_TANK_W / 2)
    assert 0 < left < right < symbols.FLOT_TANK_W
    assert top == 0.0 and bottom < BODY.height
    # Half a pitch: an arrowhead on the air line clears the shaft.
    assert BODY.ports["air"][0] - shaft_x >= MIN_NOZZLE_PITCH / 2


def test_the_agitator_is_a_choice_fixed_at_construction():
    """Check that ``agitator=`` takes a group-28 name or ``None``, and nothing else."""
    assert _parts(FlotationCell("FC-101", agitator=None)) == ()
    cell = FlotationCell("FC-102", agitator="impeller")
    assert [(o.group, o.name) for o in _parts(cell)] == [(28, "impeller")]
    with pytest.raises(ValueError, match="paddle wheel"):
        FlotationCell("FC-103", agitator="paddle wheel")
    with pytest.raises(AttributeError):
        cell.agitator = "anchor"


def test_a_cell_draws_on_a_sheet_and_is_scheduled():
    """Check a cell piped on all four nozzles renders clean and is listed."""
    fs = Flowsheet("Rougher")
    feed = fs.add(Feed("Conditioned Slurry"))
    blower = fs.add(Blower("B-101", description="Flotation Air Blower"))
    cell = fs.add(FlotationCell("FC-101", description="Rougher Cell"))
    concentrate = fs.add(Product("Rougher Concentrate"))
    tailings = fs.add(Product("Rougher Tailings"))
    fs.connect(feed.outlet, cell.feed)
    fs.connect(blower.discharge, cell.air)
    fs.connect(cell.concentrate, concentrate.inlet)
    fs.connect(cell.tailings, tailings.inlet)

    assert 'id="sym_flotation_cell_' in fs.to_svg()
    assert [i for i in fs.validate() if i.severity == "error"] == []
    assert [row["tag"] for row in fs.equipment_list()] == ["B-101", "FC-101"]
