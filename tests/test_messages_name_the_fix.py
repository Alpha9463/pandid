"""Check that a refusal or finding names the call that fixes it."""

from __future__ import annotations

import re
from collections.abc import Callable

import pytest

from pandid import (
    ControlValve,
    Feed,
    Flowsheet,
    Port,
    Product,
    Pump,
    Stream,
    Tee,
    Valve,
    Vessel,
)
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
        (_unit_to_unit, ValueError, "Its nozzles are ['discharge', 'drive', 'suction']"),
        (_into_the_station_valve, ValueError, "station's own inlet, station.inlet"),
        (_out_of_the_station_valve, ValueError, "station's own outlet, station.outlet"),
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


def _leaving(port: Port) -> Stream:
    """Return the stream leaving *port*."""
    assert port.stream is not None
    return port.stream


def _carry(fs: Flowsheet, line: Stream) -> None:
    """Put a station, two valves and three balloons on *line* and its parts."""
    valve = fs.add(Valve("HV-1"), on=line, at=0.7)
    station = fs.add_valve_station("FV-101", on=line, at=0.1)
    fs.add(Valve("HV-2"), on=line)
    fs.add_instrument("FT", 101, sensing=line, at=0.4)
    fs.add_instrument("PT", 102, sensing=_leaving(station.outlet), at=0.2)
    fs.add_instrument("PT", 103, sensing=_leaving(valve.outlet), at=0.1)


#: What the advice lists, devices in flow order and then the balloons.
_CARRIED = "valve station FV-101, HV-1, HV-2 (in flow order), FT-101, PT-102 and PT-103"


def test_the_tee_advice_lists_everything_the_line_carries() -> None:
    """Check that a tee refused on a line names its connect() calls and every item to put back."""
    fs, feed, product = _line()
    line = fs.connect(feed.outlet, product.inlet)
    _carry(fs, line)
    with pytest.raises(ValueError) as refused:
        fs.add(Tee("T"), on=line, at=0.5)
    assert (
        "fs.connect(F.outlet, T.inlet), fs.connect(T.outlet, P.inlet) and "
        "fs.connect(T.branch, ...). Then put back what S1 carries, each where it sits now: "
        + _CARRIED
    ) in str(refused.value)
