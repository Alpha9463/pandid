"""Check that a parallel bank between a splitter and a mixer draws planar."""

import pytest

from pandid import Flowsheet, ShellAndTubeExchanger, units as U
from pandid.layout.control import _flaws
from pandid.layout.layered import COL_GAP, LANE_PITCH
from pandid.layout.quality import measure_final
from pandid.route_geometry import stream_polyline
from pandid.routing.metrics import real_bends
from pandid.routing.visibility import MIN_ESCAPE


def _bank(n: int, exchangers: bool) -> Flowsheet:
    """Return n pumps, each with an exchanger if asked, between SP and MX."""
    fs = Flowsheet(f"Bank of {n}")
    feed, product = fs.add(U.Feed("F")), fs.add(U.Product("P"))
    sp = fs.add(U.Splitter("SP", n_outlets=n))
    mx = fs.add(U.Mixer("MX", n_inlets=n))
    fs.connect(feed.outlet, sp.inlet)
    fs.connect(mx.outlet, product.inlet)
    for i, (outlet, inlet) in enumerate(zip(sp.outlets, mx.inlets)):
        pump = fs.add(U.Pump(f"P-{i}"))
        fs.connect(outlet, pump.suction)
        if exchangers:
            exchanger = fs.add(ShellAndTubeExchanger(f"E-{i}"))
            fs.connect(pump.discharge, exchanger.tube_in)
            fs.connect(exchanger.tube_out, inlet)
        else:
            fs.connect(pump.discharge, inlet)
    return fs


@pytest.mark.parametrize(("n", "exchangers"), [(6, False), (4, True), (8, True), (16, True)])
def test_a_parallel_bank_draws_without_crossings_or_crowding(n, exchangers):
    fs = _bank(n, exchangers)
    fs.route()
    assert measure_final(fs).crossings == 0
    codes = {issue.code for issue in fs.validate()}
    assert not codes & {"nozzles-crowded", "lines-crowded"}
    assert _flaws(fs)["line-on-line"] == 0
    # A lateral turns twice at most, so none loops round its header.
    for s in fs.streams:
        if {s.source.owner.name, s.dest.owner.name} & {"SP", "MX"}:
            assert real_bends(stream_polyline(s)) <= 2, s.name


def test_a_header_face_grows_with_its_nozzles_and_keeps_a_stated_height():
    fs = Flowsheet("Headers")
    two, six = fs.add(U.Mixer("M-1")), fs.add(U.Mixer("M-2", n_inlets=6))
    stated = fs.add(U.Splitter("SP-1", n_outlets=6, height=80))
    fs.layout()
    assert two.frame is not None and six.frame is not None and stated.frame is not None
    assert (two.frame.w, two.frame.h) == (50, 50)
    assert (six.frame.w, six.frame.h) == (50, 130)
    assert stated.frame.h == 80


def test_a_layer_gap_widens_to_give_each_lateral_a_lane():
    fs = _bank(16, exchangers=False)
    fs.layout()
    sp, pump = fs.units[2], fs.units[4]
    assert sp.frame is not None and pump.frame is not None
    # Seven laterals overlap on the way up, needing eight pitches.
    assert pump.frame.x - (sp.frame.x + sp.frame.w) == 2 * MIN_ESCAPE + 8 * LANE_PITCH
    assert 2 * MIN_ESCAPE + 8 * LANE_PITCH > COL_GAP
