# tests/test_flowsheet.py
import pytest
from pfd import Flowsheet, units as U


def _fs():
    fs = Flowsheet("Test")
    feed = fs.add(U.Feed("Feed"))
    pump = fs.add(U.Pump("K-101"))
    prod = fs.add(U.Product("Prod"))
    return fs, feed, pump, prod


def test_connect_creates_stream_and_marks_ports():
    fs, feed, pump, prod = _fs()
    s = fs.connect(feed.outlet, pump.suction)
    assert s in fs.streams
    assert s.name == "S1"
    assert s.kind == "material"
    assert feed.outlet.stream is s
    assert pump.suction.stream is s


def test_auto_stream_names_increment():
    fs, feed, pump, prod = _fs()
    fs.connect(feed.outlet, pump.suction)
    s2 = fs.connect(pump.discharge, prod.inlet)
    assert s2.name == "S2"


def test_connect_rejects_wrong_directions():
    fs, feed, pump, prod = _fs()
    with pytest.raises(ValueError, match="must be an outlet"):
        fs.connect(pump.suction, prod.inlet)  # suction is an inlet
    with pytest.raises(ValueError, match="must be an inlet"):
        fs.connect(feed.outlet, pump.discharge)  # discharge is an outlet


def test_connect_rejects_already_connected_port():
    fs, feed, pump, prod = _fs()
    fs.connect(feed.outlet, pump.suction)
    with pytest.raises(ValueError, match="already connected"):
        fs.connect(feed.outlet, prod.inlet)  # feed.outlet reused


def test_connect_rejects_unit_not_added():
    fs, feed, pump, prod = _fs()
    stray = U.Product("Stray")  # never added to fs
    with pytest.raises(ValueError, match="added to this flowsheet"):
        fs.connect(pump.discharge, stray.inlet)


def test_energy_streams_auto_detected():
    fs = Flowsheet("Test")
    heater = fs.add(U.Heater("E-1"))  # heater.duty is an inlet energy port
    cooler = fs.add(U.Cooler("C-1"))  # cooler.duty is an outlet energy port
    s = fs.connect(cooler.duty, heater.duty)  # both roles == "energy"
    assert s.kind == "energy"


def test_named_connect_overrides_auto_name():
    fs, feed, pump, prod = _fs()
    s = fs.connect(feed.outlet, pump.suction, name="feed-to-pump")
    assert s.name == "feed-to-pump"


def test_add_rejects_duplicate_unit():
    fs = Flowsheet("Test")
    pump = U.Pump("K-1")
    fs.add(pump)
    with pytest.raises(ValueError, match="already on this flowsheet"):
        fs.add(pump)


def test_add_rejects_duplicate_unit_name():
    fs = Flowsheet("Test")
    fs.add(U.Pump("K-1"))
    with pytest.raises(ValueError, match="already exists on this flowsheet"):
        fs.add(U.Pump("K-1"))


def test_connect_rejects_invalid_stream_kind():
    fs, feed, pump, prod = _fs()
    with pytest.raises(ValueError, match="Stream kind must be"):
        fs.connect(feed.outlet, pump.suction, kind="magic")


def test_add_rejects_unit_from_another_flowsheet():
    fs1 = Flowsheet("FS1")
    fs2 = Flowsheet("FS2")
    pump = U.Pump("K-1")
    fs1.add(pump)
    with pytest.raises(ValueError, match="already on flowsheet"):
        fs2.add(pump)
