"""Test the schedules a sheet emits as rows: lines, equipment and instruments."""

import csv
import io
import re

import pytest

from pandid import ControlValve, Feed, Flowsheet, GearPump, Product, Valve, Vessel
from pandid.deprecation import CODE
from pandid.document import equipment_list, equipment_table
from pandid.render.furniture import stream_table_layout


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


def test_the_line_list_has_one_row_per_line():
    """Check the line list's rows on a small sheet, the split suction once."""
    assert _sheet().line_list() == [
        {
            "line": '4"-P-1001-A1A',
            "kind": "material",
            "size": '4"',
            "schedule": None,
            "service": "P",
            "spec": "A1A",
            "insulation": None,
            "from_unit": "Feed",
            "from_nozzle": "outlet",
            "to_unit": "P-101",
            "to_nozzle": "suction",
            "Temperature": "25 C",
            "Pressure": None,
        },
        {
            "line": "S2",
            "kind": "material",
            "size": None,
            "schedule": None,
            "service": None,
            "spec": None,
            "insulation": None,
            "from_unit": "P-101",
            "from_nozzle": "discharge",
            "to_unit": "V-101",
            "to_nozzle": "in_1",
            "Temperature": None,
            "Pressure": "4 barg",
        },
        {
            "line": "S3",
            "kind": "material",
            "size": None,
            "schedule": None,
            "service": None,
            "spec": None,
            "insulation": None,
            "from_unit": "V-101",
            "from_nozzle": "out_1",
            "to_unit": "Product",
            "to_nozzle": "inlet",
            "Temperature": None,
            "Pressure": None,
        },
    ]


def test_a_split_line_is_one_row_that_agrees_with_the_stream_table():
    """Check that a split line is one row reporting the stream table's values."""
    fs = Flowsheet("Split")
    feed = fs.add(Feed("Feed"))
    product = fs.add(Product("Product"))
    line = fs.connect(feed.outlet, product.inlet)
    fs.add(Valve("HV-101"), on=line)
    first, second = [s for s in fs.streams if s.name == line.name]
    first.properties = {"Temperature": "20 C"}
    second.properties = {"Temperature": "90 C", "Pressure": "3 barg"}
    second.tabulate = True

    table = stream_table_layout(fs)
    assert table is not None
    drawn = {row[0].text: row[1].text for row in table.rows}
    (row,) = fs.line_list()
    assert (row["line"], row["Temperature"], row["Pressure"]) == (
        drawn["Stream Number"],
        drawn["Temperature"],
        drawn["Pressure"],
    )
    assert (row["from_unit"], row["to_unit"]) == ("Feed", "Product")


def _ends(row: dict) -> list:
    """Return a line-list row's from and to unit and nozzle."""
    return [row[k] for k in ("from_unit", "from_nozzle", "to_unit", "to_nozzle")]


def test_a_line_back_to_its_own_unit_keeps_both_ends():
    """Check that a line through a valve back to its unit names both nozzles."""
    fs = Flowsheet("Return")
    drum = fs.add(Vessel("V-101"))
    line = fs.connect(drum.outlet, drum.in_1)
    fs.add(Valve("HV-101"), on=line)
    (row,) = fs.line_list()
    assert _ends(row) == ["V-101", "out_1", "V-101", "in_1"]


def test_a_station_with_numbered_drains_runs_to_its_equipment():
    """Check that drain valves carrying the line's number are not its ends."""
    fs = Flowsheet("Station")
    feed = fs.add(Feed("Feed"))
    drum = fs.add(Vessel("V-101"))
    number = {"size": '4"', "service": "P", "sequence": 101, "spec": "A1A"}
    station = fs.add_valve_station("CV-101", drains=2, **number)
    fs.connect(feed.outlet, station.inlet, **number)
    fs.connect(station.outlet, drum.in_1, **number)
    (row,) = fs.line_list()
    assert _ends(row) == ["Feed", "outlet", "V-101", "in_1"]


def test_a_stream_number_shared_across_a_pump_runs_through_it():
    """Check that a stream number given to both sides of a pump spans it."""
    fs = Flowsheet("Shared")
    drum = fs.add(Vessel("V-401"))
    pump = fs.add(GearPump("P-402"))
    product = fs.add(Product("Product"))
    fs.connect(drum.outlet, pump.suction, name="S-409")
    fs.connect(pump.discharge, product.inlet, name="S-409")
    (row,) = fs.line_list()
    assert _ends(row) == ["V-401", "out_1", "Product", "inlet"]


def test_a_property_named_like_a_column_is_refused_with_advice_that_keeps_it():
    """Check that following the clash advice literally keeps every property."""
    fs = Flowsheet("Clash")
    feed = fs.add(Feed("Feed"))
    product = fs.add(Product("Product"))
    line = fs.connect(feed.outlet, product.inlet, size='2"')
    line.properties = {"Temperature": "25 C", "size": "DN50", "Flow (kg/h)": 1200}
    with pytest.raises(ValueError, match=re.escape(line.name)) as refused:
        fs.line_list()
    advice = str(refused.value).rsplit(": ", 1)[1]
    exec(advice, {"stream": line})
    assert line.properties == {"Temperature": "25 C", "Flow (kg/h)": 1200, "Size": "DN50"}
    (row,) = fs.line_list()
    assert (row["size"], row["Size"], row["Temperature"]) == ('2"', "DN50", "25 C")


def test_the_equipment_list_has_one_row_per_scheduled_unit():
    """Check the equipment list's rows match the drawn table's default units."""
    fs = _sheet()
    rows = fs.equipment_list()
    assert rows == [
        {
            "tag": "P-101",
            "description": "Transfer Pump",
            "class": "GearPump",
            "variant": "gear",
        },
        {"tag": "V-101", "description": "Vessel", "class": "Vessel", "variant": "default"},
    ]
    assert [(r["tag"], r["description"]) for r in rows] == equipment_table(fs).rows


def test_the_instrument_index_has_one_row_per_balloon():
    """Check the instrument index's rows on a small sheet."""
    assert _sheet().instrument_index() == [
        {
            "tag": "FT-101",
            "loop": "F-101",
            "measured_variable": "F",
            "function_letters": "FT",
            "location": "field",
            "on": '4"-P-1001-A1A',
            "relation": "sensing",
        },
        {
            "tag": "FIC-101",
            "loop": "F-101",
            "measured_variable": "F",
            "function_letters": "FIC",
            "location": "central",
            "on": "FT-101",
            "relation": "near",
        },
        {
            "tag": "LI-102",
            "loop": "L-102",
            "measured_variable": "L",
            "function_letters": "LI",
            "location": "field",
            "on": "V-101",
            "relation": "sensing",
        },
    ]


def test_an_instruments_loop_is_its_loops_name():
    """Check that each balloon's ``loop`` is the name of the loop it was built from."""
    fs = Flowsheet("Loops")
    feed = fs.add(Feed("Feed"))
    valve = fs.add(ControlValve("FV-101"))
    product = fs.add(Product("Product"))
    line = fs.connect(feed.outlet, valve.inlet)
    fs.connect(valve.outlet, product.inlet)
    flow = fs.add_control_loop("F", 101, measuring=line, acting_on=valve).loop
    pressure = fs.add_loop("P")
    fs.add_instrument("PDT", pressure, sensing=line)
    fs.add_instrument("pi", pressure, near=valve)
    rows = {row["tag"]: row["loop"] for row in fs.instrument_index()}
    assert rows == {
        "FT-101": flow.name,
        "FIC-101": flow.name,
        f"PDT-{pressure.number}": pressure.name,
        f"pi-{pressure.number}": pressure.name,
    }


@pytest.mark.parametrize("schedule", ["line_list", "equipment_list", "instrument_index"])
def test_each_schedule_round_trips_through_csv(schedule: str):
    """Check that ``csv.DictWriter`` writes a schedule that reads back the same."""
    rows = getattr(_sheet(), schedule)()
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    buffer.seek(0)
    text = [{k: "" if v is None else str(v) for k, v in row.items()} for row in rows]
    assert list(csv.DictReader(buffer)) == text


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
