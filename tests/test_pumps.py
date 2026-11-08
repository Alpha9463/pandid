"""Check the ISO 10628-2 group-15 pumps and the practice pumps beside them."""

import pytest

from pandid import (
    DiaphragmPump,
    Feed,
    Flowsheet,
    LobePump,
    Product,
    ProgressiveCavityPump,
    Pump,
    ReciprocatingPump,
    VerticalTurbinePump,
)
from pandid.portgeom import outward_dir
from pandid.render.symbols import default_registry

#: Table 2's grid module, in drawing units.
M = 10.0

#: Each new class, the variant it draws and its registration number.
CLASSES = [
    (ProgressiveCavityPump, "progressive_cavity", "X8093"),
    (ReciprocatingPump, "reciprocating", "X8094"),
    (DiaphragmPump, "diaphragm", "X8095"),
    (LobePump, "lobe", ""),
    (VerticalTurbinePump, "vertical_turbine", ""),
]


@pytest.mark.parametrize("cls,variant,reg", CLASSES, ids=[c[1] for c in CLASSES])
def test_each_pump_class_draws_its_variant(cls, variant: str, reg: str):
    """Check that each class draws its own registered pump."""
    pump = cls("P-1")
    sym = default_registry.for_unit(pump)
    assert pump.variant == variant
    assert sym is default_registry.get("pump", variant)
    assert sym is default_registry.for_unit(Pump("P-2", variant=variant))
    assert sym.iso_reg == reg


@pytest.mark.parametrize("variant", ["progressive_cavity", "reciprocating", "diaphragm", "lobe"])
def test_a_group_15_pump_is_the_six_module_circle(variant: str):
    """Check the 15.1 outline: suction W, discharge at the chevron's apex E, drive on the crown."""
    sym = default_registry.get("pump", variant)
    assert (sym.width, sym.height) == (6 * M, 6 * M)
    assert sym.ports == {
        "suction": (0.0, 3 * M),
        "discharge": (6 * M, 3 * M),
        "drive": (3 * M, 0.0),
    }


def test_a_vertical_turbine_pump_draws_from_below_and_discharges_from_its_head():
    """Check the bowl's suction faces down and the head's discharge faces east."""
    sym = default_registry.get("pump", "vertical_turbine")
    w, h = sym.width, sym.height
    assert outward_dir(*sym.ports["suction"], w, h) == "S"
    assert outward_dir(*sym.ports["discharge"], w, h) == "E"
    assert sym.gravity_fixed


def test_a_line_through_each_new_pump_draws_clean(tmp_path):
    """Check that every new pump renders on a line and validates."""
    fs = Flowsheet("Pumps")
    for i, (cls, _variant, _reg) in enumerate(CLASSES, start=1):
        pump = fs.add(cls(f"P-{i}"))
        fs.connect(fs.add(Feed(f"F-{i}")).outlet, pump.suction)
        fs.connect(pump.discharge, fs.add(Product(f"O-{i}")).inlet)
    fs.render(str(tmp_path / "pumps.svg"), diagram="p&id")
    assert fs.validate() == []
    fs.render(str(tmp_path / "pumps.drawio"), diagram="p&id")
