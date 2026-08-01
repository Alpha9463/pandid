"""Stream numbering: inline valves carry the number through; signals unnumbered.

The number ``connect()`` hands back is the number the sheet gets drawn with:
a report, a stream table or a label written from ``s.name`` before the render
must not disagree with the drawing.
"""

from pandid import Flowsheet, units as U


def test_valve_carries_stream_number():
    fs = Flowsheet("v")
    f = fs.add(U.Feed("F"))
    v = fs.add(U.Valve("FV-1"))
    p = fs.add(U.Product("P"))
    s1 = fs.connect(f.outlet, v.inlet)
    s2 = fs.connect(v.outlet, p.inlet)
    fs.renumber_streams()
    assert s1.name == s2.name == "S1"  # one number through the inline valve


def test_new_line_number_valve_breaks_number():
    fs = Flowsheet("v")
    f = fs.add(U.Feed("F"))
    v = fs.add(U.Valve("FV-1"))
    p = fs.add(U.Product("P"))
    v.new_line_number = True
    s1 = fs.connect(f.outlet, v.inlet)
    s2 = fs.connect(v.outlet, p.inlet)
    fs.renumber_streams()
    assert s1.name != s2.name  # important valve breaks the number


def test_reactor_breaks_number():
    fs = Flowsheet("r")
    f = fs.add(U.Feed("F"))
    r = fs.add(U.Reactor("R"))
    p = fs.add(U.Product("P"))
    s1 = fs.connect(f.outlet, r.feed)
    s2 = fs.connect(r.outlet, p.inlet)
    fs.renumber_streams()
    assert s1.name != s2.name


def test_fitting_carries_stream_number():
    fs = Flowsheet("f")
    f = fs.add(U.Feed("F"))
    st = fs.add(U.Fitting("ST-1", variant="strainer"))
    p = fs.add(U.Product("P"))
    s1 = fs.connect(f.outlet, st.inlet)
    s2 = fs.connect(st.outlet, p.inlet)
    fs.renumber_streams()
    assert s1.name == s2.name == "S1"  # a strainer is inline, like a valve


def test_connect_returns_the_number_that_gets_drawn():
    fs = Flowsheet("n")
    f = fs.add(U.Feed("F"))
    v = fs.add(U.Valve("FV-1"))
    st = fs.add(U.Fitting("ST-1", variant="strainer"))
    p = fs.add(U.Product("P"))
    streams = [
        fs.connect(f.outlet, v.inlet),
        fs.connect(v.outlet, st.inlet),
        fs.connect(st.outlet, p.inlet),
    ]
    held = [s.name for s in streams]
    svg = fs.to_svg()
    fs.to_svg()  # and again: renumbering is idempotent
    assert [s.name for s in streams] == held  # rendering did not move them
    assert held == ["S1", "S1", "S1"]  # one number through both inline fittings
    assert ">S1<" in svg


def test_explicit_names_are_never_renumbered():
    fs = Flowsheet("n")
    f = fs.add(U.Feed("F"))
    p = fs.add(U.Pump("P-1"))
    prod = fs.add(U.Product("P"))
    named = fs.connect(f.outlet, p.suction, name="100-BFW-01")
    auto = fs.connect(p.discharge, prod.inlet)
    assert (named.name, auto.name) == ("100-BFW-01", "S1")
    fs.to_svg()
    assert (named.name, auto.name) == ("100-BFW-01", "S1")


def test_new_line_number_set_after_connecting_renumbers():
    fs = Flowsheet("n")
    f = fs.add(U.Feed("F"))
    v = fs.add(U.Valve("FV-1"))
    p = fs.add(U.Product("P"))
    s1 = fs.connect(f.outlet, v.inlet)
    s2 = fs.connect(v.outlet, p.inlet)
    assert s1.name == s2.name == "S1"  # inline until the valve is called important
    v.new_line_number = True
    assert (s1.name, s2.name) == ("S1", "S2")  # the break lands without a render


def test_energy_stream_does_not_take_a_process_number():
    """A duty line is drawn with a number, but not one from the process run."""
    fs = Flowsheet("e")
    f = fs.add(U.Feed("F"))
    heater = fs.add(U.Heater("E-1"))
    cooler = fs.add(U.Cooler("C-1"))
    p = fs.add(U.Product("P"))
    duty = fs.connect(cooler.utility_out, heater.utility_in)  # both energy ports
    s1 = fs.connect(f.outlet, heater.inlet)
    s2 = fs.connect(heater.outlet, p.inlet)
    assert duty.kind == "energy"
    assert (s1.name, s2.name) == ("S1", "S2")  # the duty line burned no number
    assert duty.name == "S3"  # numbered after the process streams, not before
    fs.to_svg()
    assert (s1.name, s2.name, duty.name) == ("S1", "S2", "S3")


def test_signal_line_does_not_take_a_process_number():
    fs = Flowsheet("s")
    f = fs.add(U.Feed("F"))
    fv = fs.add(U.Valve("FV-1"))
    p = fs.add(U.Product("P"))
    fic = fs.add_instrument("FIC", 1)
    sig = fs.connect(fic.sig_out, fv.actuator, kind="electric")
    s1 = fs.connect(f.outlet, fv.inlet)
    s2 = fs.connect(fv.outlet, p.inlet)
    assert s1.name == s2.name == "S1"
    assert sig.name == "S2"  # last in the sequence, so it shares no name


# --- stream_number_start ------------------------------------------------------


def _two_streams(**kwargs):
    """Feed -> pump -> product: a pump breaks the number, so two of them."""
    fs = Flowsheet("start", **kwargs)
    f = fs.add(U.Feed("F"))
    p = fs.add(U.Pump("P-1"))
    prod = fs.add(U.Product("P"))
    return fs, [fs.connect(f.outlet, p.suction), fs.connect(p.discharge, prod.inlet)]


def test_stream_number_start_moves_the_whole_series():
    fs, streams = _two_streams(stream_number_start=100)
    assert [s.name for s in streams] == ["S100", "S101"]
    fs.to_svg()
    assert [s.name for s in streams] == ["S100", "S101"]  # and rendering did not move them


def test_stream_number_start_defaults_to_one():
    _, streams = _two_streams()
    assert [s.name for s in streams] == ["S1", "S2"]


def test_stream_number_start_reaches_a_callable_scheme_too():
    """The offset is on the number, not inside the format string, so the two
    spellings of a naming scheme are handed the same ``n``."""
    fs, streams = _two_streams(stream_naming_scheme=lambda n: f"S{n:03d}", stream_number_start=100)
    assert [s.name for s in streams] == ["S100", "S101"]


def test_stream_number_start_is_not_the_line_sequence():
    """Two numbers on two lists: ``stream_number_start`` moves the ``S1`` a flag
    draws, ``line_number_start`` the ``1001`` inside ``6"-P-1001``. A sheet can
    move one and leave the other, so neither stands in for the other.
    """
    fs = Flowsheet("both", stream_number_start=100, line_number_start=301)
    f = fs.add(U.Feed("F"))
    p = fs.add(U.Pump("P-1"))
    prod = fs.add(U.Product("Prod"))
    plain = fs.connect(f.outlet, p.suction)
    numbered = fs.connect(p.discharge, prod.inlet, size='6"', service="P", spec="A1A")
    assert plain.name == "S100"  # the stream series
    assert numbered.name == '6"-P-302-A1A'  # the line series, second group


def test_stream_number_start_round_trips_through_a_spec():
    fs, _ = _two_streams(stream_number_start=100)
    spec = fs.to_dict()
    assert spec["stream_number_start"] == 100
    rebuilt = Flowsheet.from_dict(spec)
    assert rebuilt.stream_number_start == 100
    assert [s.name for s in rebuilt.streams] == ["S100", "S101"]


def test_a_default_stream_number_start_writes_no_key():
    assert "stream_number_start" not in Flowsheet("plain").to_dict()


def test_signals_unnumbered_and_no_arrow():
    fs = Flowsheet("s")
    a = fs.add(U.Instrument("FT-1"))
    b = fs.add(U.Instrument("FIC-1"))
    sig = fs.connect(a.sig_out, b.sig_in, kind="electric")
    svg = fs.to_svg()
    # the signal name is not drawn as an inline label
    assert f">{sig.name}<" not in svg
