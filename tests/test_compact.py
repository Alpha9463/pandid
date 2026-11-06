"""Check that route() closes the empty bands across a drawing."""

from __future__ import annotations

import pytest

from pandid import Flowsheet, units as U
from pandid.layout.attach import stream_path
from pandid.layout.compact import empty_bands
from pandid.portgeom import unit_box
from pandid.routing.lanes import _score
from _layout_cases import frame_of

Box = tuple[float, float, float, float]


def _chain() -> Flowsheet:
    """Return a drum, pump and drum in line, with an LT and LIC hung east of the first.

    Layout leaves a band clear of everything but a line between the LIC
    and the pump.
    """
    fs = Flowsheet("chain")
    drum = fs.add(U.Vessel("V-101"))
    pump = fs.add(U.Pump("P-101"))
    fs.connect(drum.outlet, pump.suction)
    fs.connect(pump.discharge, fs.add(U.Vessel("V-102")).inlet)
    lt = fs.add_instrument("LT", 101, sensing=drum, face="E")
    fs.add_instrument("LIC", 101, near=lt, face="E")
    return fs


def _open_chain(monkeypatch: pytest.MonkeyPatch) -> Flowsheet:
    """Return the chain routed with its empty bands left open."""
    fs = _chain()
    with monkeypatch.context() as patch:
        patch.setattr(Flowsheet, "_close_bands", lambda self: None)
        fs.route()
    return fs


def _boxes(fs: Flowsheet) -> dict[str, Box]:
    """Return every unit's drawn box, by name."""
    return {u.name: unit_box(u, frame_of(u)) for u in fs.units}


def _turns(fs: Flowsheet) -> list[list[tuple[bool, bool, bool, bool]]]:
    """Return which way each run of each line heads."""
    return [
        [(bx > ax, bx < ax, by > ay, by < ay) for (ax, ay), (bx, by) in zip(path, path[1:])]
        for path in map(stream_path, fs.streams)
    ]


def _width(boxes: dict[str, Box]) -> float:
    """Return the width the boxes span."""
    return max(b[2] for b in boxes.values()) - min(b[0] for b in boxes.values())


def test_route_closes_an_empty_band_and_keeps_every_line_s_turns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Check that the pump and what lies past it move in, and no line turns another way."""
    open_ = _open_chain(monkeypatch)
    fs = _chain()
    fs.route()

    before, after = _boxes(open_), _boxes(fs)
    assert empty_bands(open_) != ([], [])
    assert empty_bands(fs) == ([], [])
    assert _width(after) < _width(before)
    assert after["P-101"][0] < before["P-101"][0]
    assert {k: after[k] for k in ("V-101", "LT-101", "LIC-101")} == {
        k: before[k] for k in ("V-101", "LT-101", "LIC-101")
    }
    assert _turns(fs) == _turns(open_)
    assert _score(fs)[0] == _score(open_)[0]
    assert not _score(fs)[1]


def test_a_pinned_sheet_keeps_its_empty_band(monkeypatch: pytest.MonkeyPatch) -> None:
    """Check that a band with a pin on each side stays open."""
    open_ = _open_chain(monkeypatch)
    fs = _chain()
    for u in fs.units:
        if u.kind != "instrument":
            twin = next(t for t in open_.units if t.name == u.name)
            u.pin(x=frame_of(twin).x, y=frame_of(twin).y)
    fs.route()

    assert _boxes(fs) == _boxes(open_)


def test_a_band_before_a_pin_closes_toward_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """Check that the free units before a pinned pump move east to it, and the pump stays."""
    open_ = _open_chain(monkeypatch)
    pinned = frame_of(next(u for u in open_.units if u.name == "P-101"))
    fs = _chain()
    pump = next(u for u in fs.units if u.name == "P-101")
    pump.pin(x=pinned.x, y=pinned.y)
    fs.route()

    before, after = _boxes(open_), _boxes(fs)
    assert (frame_of(pump).x, frame_of(pump).y) == (pinned.x, pinned.y)
    assert after["V-101"][0] > before["V-101"][0]
    assert _width(after) < _width(before)
    assert _turns(fs) == _turns(open_)


def test_three_routes_draw_the_same_closed_sheet() -> None:
    """Check that routing again neither closes a band twice nor reopens it."""
    fs = _chain()
    drawn = []
    for _ in range(3):
        fs.route()
        drawn.append((_boxes(fs), [stream_path(s) for s in fs.streams], _score(fs)))

    assert drawn[0] == drawn[1] == drawn[2]
