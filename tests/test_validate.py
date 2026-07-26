"""Validation: hard errors raise from render(); soft issues warn."""

import pytest

from pfd import Flowsheet, units as U


def test_overlapping_pins_raise():
    fs = Flowsheet("overlap")
    a = fs.add(U.Reactor("R1")).pin(x=100, y=100)
    b = fs.add(U.Reactor("R2")).pin(x=110, y=110)  # sits on top of R1
    fs.connect(a.outlet, b.feed)
    with pytest.raises(ValueError, match="overlap"):
        fs.to_svg()


def test_negative_pin_raises():
    fs = Flowsheet("oob")
    a = fs.add(U.Feed("F")).pin(x=-50, y=10)
    b = fs.add(U.Product("P")).pin(x=200, y=10)
    fs.connect(a.outlet, b.inlet)
    with pytest.raises(ValueError, match="negative|off-sheet"):
        fs.to_svg()


def test_check_false_bypasses_validation():
    fs = Flowsheet("overlap-bypass")
    a = fs.add(U.Reactor("R1")).pin(x=100, y=100)
    b = fs.add(U.Reactor("R2")).pin(x=110, y=110)
    fs.connect(a.outlet, b.feed)
    svg = fs.to_svg(check=False)  # must not raise
    assert "<svg" in svg


def test_clean_flowsheet_has_no_errors():
    fs = Flowsheet("clean")
    f = fs.add(U.Feed("F"))
    r = fs.add(U.Reactor("R"))
    p = fs.add(U.Product("P"))
    fs.connect(f.outlet, r.feed)
    fs.connect(r.outlet, p.inlet)
    fs.layout()
    fs.route()
    errors = [i for i in fs.validate() if i.severity == "error"]
    assert errors == []


# --- coincident connected ports ----------------------------------------------


def _loop_with_a_balloon():
    """A controller taking a signal in and driving a valve, plus its process tap.

    A balloon is a circle, so all three of its connections offer all four faces
    and the symbol-level duplicate-nozzle check must let those menus overlap.
    Which placement each one actually took is only visible on a laid-out sheet.
    """
    fs = Flowsheet("loop")
    feed = fs.add(U.Feed("Feed")).pin(x=60, y=170)
    fv = fs.add(U.Valve("FV-101", variant="control")).pin(x=300, y=180)
    prod = fs.add(U.Product("Product")).pin(x=520, y=170)
    fs.connect(feed.outlet, fv.inlet)
    fs.connect(fv.outlet, prod.inlet)
    lt = fs.add(U.Instrument("LT-101")).pin(x=300, y=400)
    lic = fs.add(U.Instrument("LIC-101", variant="panel")).pin(x=300, y=520)
    fs.connect(lt.sig_out, lic.sig_in, kind="electric")
    fs.connect(lic.sig_out, fv.actuator, kind="electric")
    return fs, lic


def test_two_live_connections_on_one_point_are_an_error():
    fs, lic = _loop_with_a_balloon()
    # Both named, because an override is the only way onto one point: the engine
    # picks a free face for anything the author leaves open.
    lic.nozzle("sig_in", "W")
    lic.nozzle("sig_out", "W")
    fs.layout()
    errors = [i for i in fs.validate() if i.severity == "error"]
    assert [i.code for i in errors] == ["coincident-ports"]
    assert "LIC-101.sig_in and LIC-101.sig_out" in errors[0].message
    with pytest.raises(ValueError, match="coincident-ports"):
        fs.to_svg()


def test_distinct_placements_on_the_same_balloon_are_fine():
    fs, lic = _loop_with_a_balloon()
    lic.nozzle("sig_out", "N")
    fs.layout()
    assert [i for i in fs.validate() if i.code == "coincident-ports"] == []


def test_ports_the_symbol_never_anchored_warn_rather_than_raise(gapped_kind):
    """Ports a symbol does not anchor fall back to the centre of the box, so
    they coincide by construction. That is a gap in the symbol, not a
    contradiction on the sheet, and must not stop rendering."""
    fs = Flowsheet("gapped")
    unit = fs.add(gapped_kind("G-1"))
    prod = fs.add(U.Product("P"))
    for port in ("inlet", "spare_a", "spare_b"):
        feed = fs.add(U.Feed(f"F-{port}"))
        fs.connect(feed.outlet, unit.ports[port])
    fs.connect(unit.outlet, prod.inlet)
    fs.layout()
    issues = [i for i in fs.validate() if i.code == "coincident-ports"]
    assert [i.severity for i in issues] == ["warning"]
    assert "anchors no nozzle" in issues[0].message
    fs.to_svg()  # must not raise


def test_a_mixers_extra_inlets_get_nozzles_of_their_own():
    """A third inlet is a real nozzle on the flat face, not a third stream
    landing in the middle of the symbol on the box-centre fallback."""
    fs = Flowsheet("wide-mixer")
    mix = fs.add(U.Mixer("M-1", n_inlets=4))
    prod = fs.add(U.Product("P"))
    for i in range(1, 5):
        feed = fs.add(U.Feed(f"F{i}"))
        fs.connect(feed.outlet, mix.ports[f"in_{i}"])
    fs.connect(mix.outlet, prod.inlet)
    fs.layout()
    assert [i for i in fs.validate() if i.code == "coincident-ports"] == []
