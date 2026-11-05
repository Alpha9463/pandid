"""Test the schedules a sheet emits as rows: lines, equipment and instruments."""

import pytest

from pandid import Feed, Flowsheet, GearPump, Product, Valve, Vessel
from pandid.deprecation import CODE
from pandid.document import equipment_list, equipment_table


def _sheet() -> Flowsheet:
    """Return a feed, a valve, a pump, a drum and a product, instrumented."""
    fs = Flowsheet("Transfer")
    feed = fs.add(Feed("Feed"))
    pump = fs.add(GearPump("P-101", description="Transfer Pump"))
    drum = fs.add(Vessel("V-101"))
    product = fs.add(Product("Product"))
    suction = fs.connect(feed.outlet, pump.suction, size='4"', service="P", spec="A1A")
    fs.add(Valve("HV-101"), on=suction)
    discharge = fs.connect(pump.discharge, drum.inlet)
    fs.connect(drum.outlet, product.inlet)
    suction.properties = {"Temperature": "25 C"}
    discharge.properties = {"Pressure": "4 barg"}
    ft = fs.add_instrument("FT", 101, sensing=suction, at=0.3)
    fs.add_instrument("FIC", 101, near=ft, display="central")
    fs.add_instrument("LI", 102, sensing=drum, face="E")
    return fs


# The drawn box's old name.


def test_the_old_box_name_warns_and_draws_the_same_box():
    """Check that ``equipment_list()`` warns, reports and builds the same box."""
    fs = _sheet()
    with pytest.warns(DeprecationWarning, match="equipment_table") as caught:
        old = equipment_list(fs, align="top", include=["V-101"])
    assert old == equipment_table(fs, align="top", include=["V-101"])
    assert [i.message for i in fs.validate() if i.code == CODE] == [str(caught[0].message)]


def test_the_old_box_name_refused_does_not_warn():
    """Check that a refused ``equipment_list()`` call raises without a finding."""
    fs = _sheet()
    with pytest.raises(ValueError, match="equipment_table"):
        equipment_list(fs, include=["P-999"])
    assert [i for i in fs.validate() if i.code == CODE] == []


def test_the_old_spec_type_warns_and_draws_the_same_box():
    """Check that ``type: equipment_list`` warns, reports and builds the same box."""
    spec = {
        "name": "Spec",
        "units": [{"kind": "Pump", "name": "P-101", "description": "Feed Pump"}],
        "annotations": [{"type": "equipment_table", "align": "top", "margin": 6}],
    }
    new = Flowsheet.from_dict(spec)
    spec["annotations"] = [{"type": "equipment_list", "align": "top", "margin": 6}]
    with pytest.warns(DeprecationWarning, match="equipment_table") as caught:
        old = Flowsheet.from_dict(spec)
    assert old.annotations == new.annotations
    assert old.to_svg() == new.to_svg()
    reported = [i.message for i in old.validate() if i.code == CODE]
    assert reported == [str(caught[0].message)]
    assert reported[0].startswith("annotations[0]: type: equipment_list")
