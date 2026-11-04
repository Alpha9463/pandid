"""Check that a refusal or finding names the call that fixes it."""

from __future__ import annotations

import re
from collections.abc import Callable

import pytest

from pandid import ControlValve, Feed, Flowsheet, Product, Pump, Splitter, Tee, Valve, Vessel
from pandid import units


def _line() -> tuple[Flowsheet, Feed, Product]:
    """Build a sheet with a feed and a product flag."""
    fs = Flowsheet("messages")
    return fs, fs.add(Feed("F")), fs.add(Product("P"))


def _unit_to_unit() -> None:
    fs = Flowsheet("messages")
    fs.connect(fs.add(Pump("P-1")), fs.add(Vessel("V-1")))


def _into_the_station_valve() -> None:
    fs, feed, _ = _line()
    fs.connect(feed.outlet, fs.add_valve_station("FV-101").control.inlet)


def _out_of_the_station_valve() -> None:
    fs, _, product = _line()
    fs.connect(fs.add_valve_station("FV-101").control.outlet, product.inlet)


def _on_a_recycle_line() -> None:
    fs, feed, product = _line()
    drum = fs.add(Vessel("V-1", inputs=2))
    split = fs.add(Splitter("SP-1"))
    fs.connect(feed.outlet, drum.port("in_1"))
    fs.connect(drum.port("out_1"), split.inlet)
    fs.connect(split.out_1, product.inlet)
    back = fs.connect(split.out_2, drum.port("in_2"), draw_as_recycle=True)
    fs.add(Valve("HV-1"), on=back)


def _tee_on_a_line() -> None:
    fs, feed, product = _line()
    fs.add(Tee(), on=fs.connect(feed.outlet, product.inlet))


def _second_loop(station: bool) -> Callable[[], None]:
    """Return a build that puts two flow loops on one control valve."""

    def build() -> None:
        fs, feed, product = _line()
        if station:
            valve = fs.add_valve_station("FV-101")
            inlet, outlet, element = valve.inlet, valve.outlet, valve.control
        else:
            element = fs.add(ControlValve("FV-101"))
            inlet, outlet = element.inlet, element.outlet
        line = fs.connect(feed.outlet, inlet)
        fs.connect(outlet, product.inlet)
        fs.add_control_loop("F", 101, measuring=line, acting_on=element)
        fs.add_control_loop("F", 102, measuring=line, acting_on=element)

    return build


def _acting_on_the_inlet() -> None:
    fs, feed, product = _line()
    valve = fs.add(ControlValve("RV-1"))
    line = fs.connect(feed.outlet, valve.inlet)
    fs.connect(valve.outlet, product.inlet)
    fs.add_control_loop("F", 101, measuring=line, acting_on=valve.inlet)


@pytest.mark.parametrize(
    ("build", "error", "says"),
    [
        (_unit_to_unit, ValueError, "Its nozzles are ['discharge', 'suction']"),
        (_into_the_station_valve, ValueError, "station's own inlet, station.inlet"),
        (_out_of_the_station_valve, ValueError, "station's own outlet, station.outlet"),
        (
            _on_a_recycle_line,
            ValueError,
            "fs.connect(SP-1.out_2, <device>.inlet, draw_as_recycle=True) and "
            "fs.connect(<device>.outlet, V-1.in_2)",
        ),
        (_tee_on_a_line, ValueError, "fs.connect(TEE.branch, ...)"),
        (lambda: getattr(units, "Condenser"), AttributeError, "from pandid import Condenser"),
        (lambda: getattr(units, "LevelTransmitter"), AttributeError, 'add_instrument("LT"'),
        (_second_loop(station=False), ValueError, "FIC-101 drives it"),
        (_second_loop(station=True), ValueError, "acting_on=FIC-101"),
        (_acting_on_the_inlet, ValueError, "acting_on=RV-1 or acting_on=RV-1.actuator"),
    ],
    ids=[
        "connect unit to unit",
        "into a station's valve",
        "out of a station's valve",
        "on= a recycle line",
        "on= a tee",
        "units.Condenser",
        "units.LevelTransmitter",
        "second loop on a valve",
        "second loop on a station",
        "acting_on= an inlet",
    ],
)
def test_a_refusal_names_the_call_that_fixes_it(
    build: Callable[[], object], error: type[Exception], says: str
) -> None:
    """Check that each refusal says what to type instead."""
    with pytest.raises(error, match=re.escape(says)):
        build()


def test_a_station_off_the_sheet_is_reported_once_with_its_own_position() -> None:
    """Check that a station at the corner gives one finding that moves the station."""
    fs, feed, product = _line()
    fs.add_valve_station("FV-101", x=0, y=0, on=fs.connect(feed.outlet, product.inlet))

    (found,) = [i.message for i in fs.validate() if i.code == "pin-out-of-bounds"]
    assert found.startswith("valve station FV-101 at x=0, y=0")
    assert "add_valve_station('FV-101', ...) x=0, y=52.5," in found


def test_stream_table_missing_on_an_instrumented_sheet_suggests_a_pid() -> None:
    """Check that a PFD carrying a control loop is told how to draw a P&ID."""
    fs, feed, product = _line()
    valve = fs.add(ControlValve("FV-101"))
    line = fs.connect(feed.outlet, valve.inlet)
    fs.connect(valve.outlet, product.inlet)
    fs.add_control_loop("F", 101, measuring=line, acting_on=valve)

    (found,) = [i.message for i in fs.validate() if i.code == "stream-table-missing"]
    assert 'render with diagram="p&id"' in found
