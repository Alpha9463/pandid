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
    """A process nozzle takes one line, and a second one on it is a tee.

    Stated on the pump rather than on the flag it used to be stated on:
    ``feed.outlet`` is now a *pool* (#454), because a boundary flag is a mark
    on the sheet edge rather than a nozzle. The rule this test is about did
    not move -- see the two below it.
    """
    fs, feed, pump, prod = _fs()
    fs.connect(pump.discharge, prod.inlet)
    with pytest.raises(ValueError, match=r"K-101\.discharge is already connected"):
        fs.connect(pump.discharge, prod.inlet)  # K-101.discharge reused


def test_a_boundary_flag_takes_as_many_lines_as_the_sheet_gives_it():
    """One header entering a drawing and serving three users is ordinary, and
    three flags for one header misrepresents the plant. Each line stays a line
    of its own -- its own port, its own number -- and the flag is drawn once."""
    fs = Flowsheet("Test")
    gas = fs.add(U.Feed("Gas"))
    users = [fs.add(U.Pump(f"P-{i}")) for i in (1, 2, 3)]
    streams = [fs.connect(gas.outlet, p.suction) for p in users]

    assert list(gas.ports) == ["outlet", "outlet_2", "outlet_3"]
    assert [s.source.name for s in streams] == ["outlet", "outlet_2", "outlet_3"]
    assert len({s.name for s in streams}) == 3
    assert all(s.at_boundary for s in streams)
    # The first line still reaches the nozzle the author named, which is what
    # keeps ``gas.outlet.stream`` meaning what it always did.
    assert gas.outlet.stream is streams[0]

    flare = fs.add(U.Product("Flare"))
    out = [fs.connect(p.discharge, flare.inlet) for p in users]
    assert list(flare.ports) == ["inlet", "inlet_2", "inlet_3"]
    assert [s.dest.name for s in out] == ["inlet", "inlet_2", "inlet_3"]


def test_a_flags_members_all_leave_its_one_nozzle():
    """The whole point of the flag: it is drawn once, and every run on it
    crosses the sheet edge at the same place, pointing the same way. A member
    that took the plain nearest-edge answer would leave through the top of the
    pennant."""
    from pandid.portgeom import resolve_port

    fs = Flowsheet("Test")
    gas = fs.add(U.Feed("Gas"))
    for i in (1, 2, 3):
        fs.connect(gas.outlet, fs.add(U.Pump(f"P-{i}")).suction)
    fs.layout()
    resolved = [resolve_port(gas, gas.frame, name) for name in gas.ports]
    assert len({(r.point, r.anchor, r.face) for r in resolved}) == 1
    assert resolved[0].face == "E"
    # ...and it is a *deliberate* coincidence, so validate() does not report it
    # while it still reports every other one.
    assert not [i for i in fs.validate() if i.code == "coincident-ports"]


def test_connect_rejects_a_port_run_to_itself():
    """A signal port carries no direction, so nothing about a valve's own
    actuator stops a line being asked to run from it back to itself -- the
    one case ``must be an outlet``/``must be an inlet`` above cannot catch,
    since a signal port is neither. Undetected, it draws as a zero-length
    spike ``stream_polyline()``'s own collinear-run collapse then erases
    outright: a stream that connects, routes and renders clean while
    meaning nothing.
    """
    fs, feed, valve, fic, ft = _loop()
    with pytest.raises(ValueError, match=r"FV-101\.actuator is both the source"):
        fs.connect(valve.actuator, valve.actuator, kind="pneumatic")


def test_connect_rejects_unit_not_added():
    fs, feed, pump, prod = _fs()
    stray = U.Product("Stray")  # never added to fs
    with pytest.raises(ValueError, match="added to this flowsheet"):
        fs.connect(pump.discharge, stray.inlet)


def test_energy_streams_auto_detected():
    fs = Flowsheet("Test")
    heater = fs.add(U.Heater("E-1"))  # heater.utility_in is an inlet energy port
    cooler = fs.add(U.Cooler("C-1"))  # cooler.utility_out is an outlet energy port
    s = fs.connect(cooler.utility_out, heater.utility_in)  # both roles == "energy"
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


def test_a_refused_connect_leaves_the_sheet_as_it_found_it():
    """The #433 audit of ``connect()``: every rule it checks is checked before
    the first write, so a refusal takes nothing with it.

    The nozzle *set* is compared and not only which lines are on which nozzle,
    because the write nearest the refusals is a **mint**: a balloon's signal
    connections are a pool, and taking a fresh member for a line the other end
    then refuses would leave the balloon carrying a spare nozzle nothing
    reaches, which the debug overlay draws.
    """
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
