"""`is_recycle` is computed by layout and read-only to API callers."""

import pytest

from pfd import Flowsheet, units as U


def _loop():
    fs = Flowsheet("loop")
    feed = fs.add(U.Feed("F"))
    mix = fs.add(U.Mixer("M"))
    rx = fs.add(U.Reactor("R"))
    sep = fs.add(U.Separator("S"))
    prod = fs.add(U.Product("P"))
    fs.connect(feed.outlet, mix.in_1)
    fs.connect(mix.outlet, rx.feed)
    fs.connect(rx.outlet, sep.feed)
    fs.connect(sep.liquid, prod.inlet)
    fs.connect(sep.vapor, mix.in_2)  # recycle back-edge closing the loop
    return fs


def test_is_recycle_defaults_false_and_is_read_only():
    fs = _loop()
    s = fs.streams[0]
    assert s.is_recycle is False
    with pytest.raises(AttributeError):
        s.is_recycle = True  # callers must never set it


def test_layout_marks_the_recycle_stream():
    fs = _loop()
    fs.layout()
    recycles = [s for s in fs.streams if s.is_recycle]
    assert len(recycles) == 1
    assert recycles[0].dest.owner.name == "M"  # the edge looping back into the mixer
