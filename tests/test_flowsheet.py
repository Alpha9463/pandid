import re

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


def test_naming_scheme_is_keyword_only():
    """Check that ``stream_naming_scheme`` is keyword-only."""
    with pytest.raises(TypeError):
        Flowsheet("Test", "TB")


@pytest.mark.parametrize("scheme, field", [("S-{num}", "num"), ("S-{0}", "0")])
def test_a_naming_scheme_asking_for_an_unknown_field_is_refused_when_set(scheme, field):
    """Check that a scheme asking for a field other than ``n`` is refused when set."""
    with pytest.raises(ValueError, match=f"asks for '{field}'.*'n'"):
        Flowsheet("Test", stream_naming_scheme=scheme)
    fs = Flowsheet("Test")
    with pytest.raises(ValueError, match=f"asks for '{field}'"):
        fs.stream_naming_scheme = scheme
    assert fs.stream_naming_scheme == "S{n}"


@pytest.mark.parametrize("scheme", ["S-{n.foo}", "S-{n[0]}", "S-{n:q}", "S-{n", "S-}"])
def test_a_naming_scheme_that_cannot_format_a_number_is_refused_when_set(scheme):
    """Check that a scheme that cannot format a number is refused when set, naming it."""
    with pytest.raises(ValueError, match=re.escape(f"stream_naming_scheme {scheme!r}")):
        Flowsheet("Test", stream_naming_scheme=scheme)
    fs = Flowsheet("Test")
    with pytest.raises(ValueError, match=re.escape(f"stream_naming_scheme {scheme!r}")):
        fs.stream_naming_scheme = scheme
    assert fs.stream_naming_scheme == "S{n}"


def test_connect_rejects_wrong_directions():
    fs, feed, pump, prod = _fs()
    with pytest.raises(ValueError, match="must be an outlet"):
        fs.connect(pump.suction, prod.inlet)  # suction is an inlet
    with pytest.raises(ValueError, match="must be an inlet"):
        fs.connect(feed.outlet, pump.discharge)  # discharge is an outlet


def test_connect_rejects_already_connected_port():
    """Check that a second line on a process nozzle is refused."""
    fs, feed, pump, prod = _fs()
    fs.connect(pump.discharge, prod.inlet)
    with pytest.raises(ValueError, match=r"K-101\.discharge is already connected"):
        fs.connect(pump.discharge, prod.inlet)  # K-101.discharge reused


def test_a_boundary_flag_takes_as_many_lines_as_the_sheet_gives_it():
    """Check that a boundary flag takes a line per user on members of its connection."""
    fs = Flowsheet("Test")
    gas = fs.add(U.Feed("Gas"))
    users = [fs.add(U.Pump(f"P-{i}")) for i in (1, 2, 3)]
    streams = [fs.connect(gas.outlet, p.suction) for p in users]

    assert list(gas.ports) == ["outlet", "outlet_2", "outlet_3"]
    assert [s.source.name for s in streams] == ["outlet", "outlet_2", "outlet_3"]
    assert len({s.name for s in streams}) == 3
    assert all(s.at_boundary for s in streams)
    assert gas.outlet.stream is streams[0]

    flare = fs.add(U.Product("Flare"))
    out = [fs.connect(p.discharge, flare.inlet) for p in users]
    assert list(flare.ports) == ["inlet", "inlet_2", "inlet_3"]
    assert [s.dest.name for s in out] == ["inlet", "inlet_2", "inlet_3"]


def test_connect_rejects_a_port_run_to_itself():
    """Check that a line from a port to itself is refused."""
    fs, feed, valve, fic, ft = _loop()
    with pytest.raises(ValueError, match=r"FV-101\.actuator is both the source"):
        fs.connect(valve.actuator, valve.actuator, kind="pneumatic")


def test_connect_rejects_unit_not_added():
    fs, feed, pump, prod = _fs()
    stray = U.Product("Stray")  # never added to fs
    with pytest.raises(ValueError, match="added to this flowsheet"):
        fs.connect(pump.discharge, stray.inlet)


def test_add_rejects_duplicate_unit():
    fs = Flowsheet("Test")
    pump = U.Pump("K-1")
    fs.add(pump)
    with pytest.raises(ValueError, match="already on this flowsheet"):
        fs.add(pump)


def test_connect_rejects_invalid_stream_kind():
    fs, feed, pump, prod = _fs()
    with pytest.raises(ValueError, match="Stream kind must be"):
        fs.connect(feed.outlet, pump.suction, kind="magic")


# --- signal versus material ---------------------------------------------------


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
    """Check that a process line into a valve actuator is refused."""
    fs, feed, valve, fic, ft = _loop()
    with pytest.raises(
        ValueError,
        match=r"FV-101\.actuator is a signal connection "
        r"and F-101\.outlet is a process connection",
    ):
        fs.connect(feed.outlet, valve.actuator)


def test_connect_rejects_a_signal_leaving_a_balloon_for_a_process_nozzle():
    """Check that a signal line into a process nozzle is refused."""
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
    """Check that every signal kind may run from a balloon to a valve actuator."""
    fs, feed, valve, fic, ft = _loop()
    fs.connect(ft.sig_out, fic.sig_in, kind=kind)
    assert fs.connect(fic.sig_out, valve.actuator, kind=kind).kind == kind


def test_a_refused_connect_leaves_the_sheet_as_it_found_it():
    """Check that a refused ``connect()`` leaves streams, nozzles and lines unchanged."""
    fs, feed, valve, fic, ft = _loop()
    fs.connect(fic.sig_out, valve.actuator, kind="pneumatic")  # sig_out is now spoken for
    nozzles = {(u.name, name) for u in fs.units for name in u.ports}
    lines = {(u.name, name): p.stream for u in fs.units for name, p in u.ports.items()}
    streams = list(fs.streams)

    for src, dst, kind, match in [
        (feed.outlet, valve.actuator, "material", "signal connection"),
        (fic.sig_out, valve.inlet, "pneumatic", "signal connection"),
        (fic.sig_out, ft.sig_in, "steam", "kind must be one of"),
        (fic.sig_out, valve.actuator, "pneumatic", "already connected"),
    ]:
        with pytest.raises(ValueError, match=match):
            fs.connect(src, dst, kind=kind)

    assert list(fs.streams) == streams
    assert {(u.name, name) for u in fs.units for name in u.ports} == nozzles
    assert {(u.name, name): p.stream for u in fs.units for name, p in u.ports.items()} == lines


def test_add_rejects_unit_from_another_flowsheet():
    fs1 = Flowsheet("FS1")
    fs2 = Flowsheet("FS2")
    pump = U.Pump("K-1")
    fs1.add(pump)
    with pytest.raises(ValueError, match="already on flowsheet"):
        fs2.add(pump)
