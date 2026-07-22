"""Stream numbering: inline valves carry the number through; signals unnumbered."""

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


def test_signals_unnumbered_and_no_arrow():
    fs = Flowsheet("s")
    a = fs.add(U.Instrument("FT-1"))
    b = fs.add(U.Instrument("FIC-1"))
    sig = fs.connect(a.sig_out, b.sig_in, kind="electric")
    svg = fs.to_svg()
    # the signal name is not drawn as an inline label
    assert f">{sig.name}<" not in svg
