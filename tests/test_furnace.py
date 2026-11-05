"""Check the furnace drawings: the fired heater, ISO 4.3 and the combustion chamber."""

import pytest

from pandid import CombustionChamber, Feed, Flowsheet, Furnace, Product
from pandid.portgeom import port_faces


def test_the_combustion_chamber_is_a_furnace_drawn_as_item_4_5():
    """Check that ``CombustionChamber`` draws the furnace kind's chamber."""
    chamber = CombustionChamber("FH-901")
    assert (chamber.kind, chamber.variant) == ("furnace", "combustion_chamber")
    assert isinstance(chamber, Furnace)


@pytest.mark.parametrize(
    ("variant", "faces"),
    [
        ("general", {"inlet": "W", "outlet": "E", "fuel": "S"}),
        ("combustion_chamber", {"inlet": "W", "outlet": "N", "fuel": "S"}),
    ],
)
def test_each_nozzle_leaves_by_its_own_face(variant, faces):
    """Check the face each furnace nozzle leaves by."""
    unit = Furnace("F-101", variant=variant)
    assert {name: port_faces(unit, name)[0] for name in unit.ports} == faces


def test_an_undescribed_furnace_is_listed_by_what_it_draws():
    """Check that the equipment list names each furnace drawing for what it is."""
    fs = Flowsheet("Firing")
    fs.add(Furnace("H-101"))
    fs.add(Furnace("F-102", variant="general"))
    fs.add(CombustionChamber("FH-103"))
    rows = [(row["tag"], row["description"]) for row in fs.equipment_list()]
    assert rows == [
        ("H-101", "Fired Heater"),
        ("F-102", "Furnace"),
        ("FH-103", "Combustion Chamber"),
    ]


def test_a_combustion_chamber_draws_on_a_sheet():
    """Check a chamber fed air and fuel renders clean."""
    fs = Flowsheet("Hot gas")
    air = fs.add(Feed("Combustion Air"))
    fuel = fs.add(Feed("Fuel Gas"))
    chamber = fs.add(CombustionChamber("FH-901"))
    gas = fs.add(Product("Hot Gas"))
    fs.connect(air.outlet, chamber.inlet)
    fs.connect(fuel.outlet, chamber.fuel)
    fs.connect(chamber.outlet, gas.inlet)

    assert 'id="sym_furnace_combustion_chamber"' in fs.to_svg()
    assert [i for i in fs.validate() if i.severity == "error"] == []
