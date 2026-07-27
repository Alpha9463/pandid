import pytest
from pandid import Flowsheet, units as U


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


def test_naming_scheme_is_keyword_only():
    """``stream_naming_scheme`` takes no positional slot, so a stray second
    argument fails loudly rather than being silently adopted as the scheme."""
    with pytest.raises(TypeError):
        Flowsheet("Test", "TB")


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


# --- signal versus material ---------------------------------------------------
#
# A signal connection is a terminal for a measurement or a command: a valve's
# stem, an instrument's tap and its two signal connections. Nothing flows
# through one, so the two vocabularies do not mix in either direction.


def _loop():
    fs = Flowsheet("Loop")
    return (
        fs,
        fs.add(U.Feed("F-101")),
        fs.add(U.Valve("FV-101", variant="control")),
        fs.add(U.Instrument("FIC", 101)),
        fs.add(U.Instrument("FT", 101)),
    )


def test_connect_rejects_process_fluid_into_a_signal_connection():
    """A pipe into a valve stem is not a connection, and drawn as a process
    line it claims one that cannot exist."""
    fs, feed, valve, fic, ft = _loop()
    with pytest.raises(
        ValueError,
        match=r"FV-101\.actuator is a signal connection "
        r"and F-101\.outlet is a process connection",
    ):
        fs.connect(feed.outlet, valve.actuator)


def test_connect_rejects_process_fluid_into_an_instrument_signal_port():
    fs, feed, valve, fic, ft = _loop()
    with pytest.raises(ValueError, match=r"FIC-101\.sig_in is a signal connection"):
        fs.connect(valve.outlet, fic.sig_in)


def test_connect_rejects_a_signal_leaving_a_balloon_for_a_process_nozzle():
    """The rule reads the same from the signal end: a controller output is not
    something a pump can be piped from."""
    fs, feed, valve, fic, ft = _loop()
    pump = fs.add(U.Pump("P-101"))
    with pytest.raises(
        ValueError,
        match=r"FIC-101\.sig_out is a signal connection "
        r"and P-101\.suction is a process connection",
    ):
        fs.connect(fic.sig_out, pump.suction, kind="electric")


def test_connect_rejects_a_signal_kind_between_two_process_nozzles():
    fs, feed, valve, fic, ft = _loop()
    pump_a = fs.add(U.Pump("P-101A"))
    pump_b = fs.add(U.Pump("P-101B"))
    with pytest.raises(
        ValueError,
        match=r"P-101A\.discharge to P-101B\.suction is "
        r"process piping; kind must be one of",
    ):
        fs.connect(pump_a.discharge, pump_b.suction, kind="pneumatic")


@pytest.mark.parametrize("kind", ["material", "energy"])
def test_connect_rejects_a_process_kind_between_two_signal_connections(kind):
    fs, feed, valve, fic, ft = _loop()
    with pytest.raises(
        ValueError,
        match=r"FT-101\.sig_out to FIC-101\.sig_in is a "
        r"signal line; kind must be one of",
    ):
        fs.connect(ft.sig_out, fic.sig_in, kind=kind)


@pytest.mark.parametrize("kind", ["electric", "pneumatic", "data", "capillary", "software"])
def test_a_control_loop_closing_on_a_valve_actuator_is_accepted(kind):
    """The legal case: every signal kind runs from a balloon to the final
    control element."""
    fs, feed, valve, fic, ft = _loop()
    fs.connect(ft.sig_out, fic.sig_in, kind=kind)
    assert fs.connect(fic.sig_out, valve.actuator, kind=kind).kind == kind


def test_add_rejects_unit_from_another_flowsheet():
    fs1 = Flowsheet("FS1")
    fs2 = Flowsheet("FS2")
    pump = U.Pump("K-1")
    fs1.add(pump)
    with pytest.raises(ValueError, match="already on flowsheet"):
        fs2.add(pump)
