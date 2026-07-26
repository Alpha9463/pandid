"""Stream numbering: inline valves carry the number through; signals unnumbered.

The number ``connect()`` hands back is the number the sheet gets drawn with —
a report, a stream table or a label written from ``s.name`` before the render
must not disagree with the drawing.
"""

from pfd import Flowsheet, units as U


def test_valve_carries_stream_number():
    fs = Flowsheet("v")
    f = fs.add(U.Feed("F"))
    v = fs.add(U.Valve("FV-1"))
    p = fs.add(U.Product("P"))
    s1 = fs.connect(f.outlet, v.inlet)
    s2 = fs.connect(v.outlet, p.inlet)
    fs.renumber_streams()
    assert s1.name == s2.name == "S1"  # one number through the inline valve


def test_significant_valve_breaks_number():
    fs = Flowsheet("v")
    f = fs.add(U.Feed("F"))
    v = fs.add(U.Valve("FV-1"))
    p = fs.add(U.Product("P"))
    v.significant = True
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


def test_significant_set_after_connecting_renumbers():
    fs = Flowsheet("n")
    f = fs.add(U.Feed("F"))
    v = fs.add(U.Valve("FV-1"))
    p = fs.add(U.Product("P"))
    s1 = fs.connect(f.outlet, v.inlet)
    s2 = fs.connect(v.outlet, p.inlet)
    assert s1.name == s2.name == "S1"  # inline until the valve is called important
    v.significant = True
    assert (s1.name, s2.name) == ("S1", "S2")  # the break lands without a render


def test_energy_stream_does_not_take_a_process_number():
    """A duty line is drawn with a number, but not one from the process run."""
    fs = Flowsheet("e")
    f = fs.add(U.Feed("F"))
    heater = fs.add(U.Heater("E-1"))
    cooler = fs.add(U.Cooler("C-1"))
    p = fs.add(U.Product("P"))
    duty = fs.connect(cooler.duty, heater.duty)  # both energy ports
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


def test_signals_unnumbered_and_no_arrow():
    fs = Flowsheet("s")
    a = fs.add(U.Instrument("FT-1"))
    b = fs.add(U.Instrument("FIC-1"))
    sig = fs.connect(a.sig_out, b.sig_in, kind="electric")
    svg = fs.to_svg()
    # the signal name is not drawn as an inline label
    assert f">{sig.name}<" not in svg
