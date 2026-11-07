"""Check that a drawn sheet read back from its spec draws as it was drawn."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest

from pandid import Flowsheet, units as U
from pandid.devices import ControlValve
from pandid.portgeom import resolve_size
from pandid.streams import Stream
from _layout_cases import build_unpinned


def _bank(pumps: int = 1) -> Flowsheet:
    """Return pumps in parallel, each with a flow loop on its valved suction line."""
    fs = Flowsheet("valved loops")
    sp = fs.add(U.Splitter("SP", n_outlets=pumps))
    mx = fs.add(U.Mixer("MX", n_inlets=pumps))
    fs.connect(fs.add(U.Feed("F")).outlet, sp.inlet)
    fs.connect(mx.outlet, fs.add(U.Product("P")).inlet)
    pairs = []
    for i, (outlet, inlet) in enumerate(zip(sp.outlets, mx.inlets)):
        pump = fs.add(U.Pump(f"P-{i}"))
        line = fs.connect(outlet, pump.suction)
        fs.connect(pump.discharge, inlet)
        pairs.append((line, fs.add(ControlValve(f"FV-{10 + i}"), on=line, at=0.5)))
    for i, (line, valve) in enumerate(pairs):
        fs.add_control_loop("F", 200 + i, measuring=line, acting_on=valve)
    return fs


def _frozen(fs: Flowsheet, index: int) -> Flowsheet:
    """Route the sheet, freeze one line where it is drawn, and route again."""
    fs.route()
    line = fs.streams[index]
    assert line.route is not None
    line.via(list(line.route.waypoints))
    fs.route()
    return fs


def _read_back(fs: Flowsheet) -> Flowsheet:
    """Return the sheet built again from its spec written out as JSON."""
    return Flowsheet.from_dict(json.loads(json.dumps(fs.to_dict())))


def _drawn(fs: Flowsheet) -> tuple[str, str]:
    """Return the sheet's SVG and draw.io documents."""
    return fs.to_svg(check=False), fs.to_drawio(check=False)


def _broken(fs: Flowsheet) -> list[str]:
    """Return the findings of a line drawn through a unit or on the slant."""
    return [i.message for i in fs.validate() if i.code in ("route-crosses-unit", "route-diagonal")]


# Every line of the one-pump bank but the valve's split run.
_LINES = [0, 1, 3, 4, 5, 6]


@pytest.mark.parametrize("index", _LINES)
def test_a_frozen_line_is_drawn_as_frozen_when_read_back(index: int) -> None:
    """Check that a line frozen on the drawn sheet keeps clear of units when read back."""
    fs = _frozen(_bank(), index)
    again = _read_back(fs)
    again.route()

    assert _broken(again) == []
    assert _drawn(again) == _drawn(fs)


@pytest.mark.parametrize(
    "make",
    [lambda: _bank(), lambda: _bank(pumps=2), lambda: _frozen(_bank(), 3)],
    ids=["bank", "two-pump bank", "frozen line"],
)
def test_a_drawn_sheet_read_back_draws_the_same(make: Callable[[], Flowsheet]) -> None:
    """Check that the sheet read back draws the same SVG and draw.io, and writes the same spec."""
    fs = make()
    fs.route()
    spec = json.loads(json.dumps(fs.to_dict()))
    again = Flowsheet.from_dict(spec)

    assert _drawn(again) == _drawn(fs)
    assert again.to_dict() == spec


def _turned() -> Flowsheet:
    """Return a mirrored pump feeding an exchanger turned a quarter, with a balloon on it."""
    fs = Flowsheet("turned")
    pump = fs.add(U.Pump("P-1")).pin(mirrored="x")
    hx = fs.add(U.HeatExchanger("E-1")).pin(orientation=90)
    fs.connect(fs.add(U.Feed("F")).outlet, pump.suction)
    fs.connect(pump.discharge, hx.tube_in)
    fs.connect(hx.tube_out, fs.add(U.Product("P")).inlet)
    fs.connect(fs.add(U.Feed("CWS")).outlet, hx.shell_in)
    fs.connect(hx.shell_out, fs.add(U.Product("CWR")).inlet)
    fs.add_instrument("TI", 1, sensing=hx, face="N")
    return fs


@pytest.mark.parametrize("make", [_turned, lambda: _bank(pumps=2)], ids=["turned", "two-pump bank"])
def test_a_sheet_read_back_has_the_frames_taps_and_lines_drawn(
    make: Callable[[], Flowsheet],
) -> None:
    """Check that each unit's frame and tap, and each line's route, read back as drawn."""
    fs = make()
    fs.route()
    again = _read_back(fs)

    def drawn(sheet: Flowsheet) -> dict[str, Any]:
        return {u.name: (u.frame, getattr(u, "tap", None)) for u in sheet.units}

    assert drawn(again) == drawn(fs)
    assert [s.route for s in again.streams] == [s.route for s in fs.streams]


def test_a_stock_face_and_an_unsettled_sheet_are_read_back() -> None:
    """Check that a mixer drawn at its stock size, and a sheet left unsettled, read back so."""
    fs = Flowsheet("mixer")
    mx = fs.add(U.Mixer("MX", n_inlets=6))
    for i, inlet in enumerate(mx.inlets):
        fs.connect(fs.add(U.Feed(f"F{i}")).outlet, inlet)
    fs.connect(mx.outlet, fs.add(U.Product("P")).inlet)
    fs.route()
    frame = mx.frame
    assert frame is not None
    mx._stock_face = True
    frame.w, frame.h = resolve_size(mx, frame)
    fs.route_converged = False
    again = _read_back(fs)
    read = next(u for u in again.units if u.name == "MX")

    assert (read._stock_face, read.frame) == (True, frame)
    assert "route-not-settled" in {i.code for i in again.validate()}


def test_a_hung_controller_and_a_fallback_line_are_written() -> None:
    """Check that the two-pump bank's spec records its hung controller and fallback line."""
    fs = _bank(pumps=2)
    fs.route()
    layout = fs.to_dict()["layout"]

    assert set(layout["units"]["FIC-200"]["beside_valve"]) == {"offset", "angle"}
    assert any(isinstance(line, dict) and line["fallback"] for line in layout["lines"])


def test_only_a_drawn_sheet_writes_its_layout() -> None:
    """Check that the spec has a layout once routed, and none before or after a pin."""
    fs = _bank()
    before = fs.to_dict()
    fs.route()
    drawn = fs.to_dict()
    fs.units[0].pin(x=300, y=300)

    assert "layout" not in before
    assert "layout" in drawn
    assert "layout" not in fs.to_dict()


def _edits() -> dict[str, Callable[[Flowsheet], Any]]:
    """Return edits by name, each made on a drawn sheet."""

    def unit(fs: Flowsheet, name: str) -> U.Unit:
        return next(u for u in fs.units if u.name == name)

    def pin(fs: Flowsheet) -> None:
        sp = unit(fs, "SP")
        assert sp.frame is not None
        sp.pin(x=sp.frame.x + 40, y=sp.frame.y)

    def via(fs: Flowsheet) -> None:
        line = fs.streams[0]
        assert line.route is not None
        line.via(list(line.route.waypoints))

    def reattach(fs: Flowsheet) -> None:
        ft = unit(fs, "FT-200")
        assert isinstance(ft, U.Instrument) and isinstance(ft.host, Stream)
        ft.attach(ft.host, at=0.3)

    def add(fs: Flowsheet) -> None:
        fs.connect(fs.add(U.Feed("F-2")).outlet, fs.add(U.Product("P-2")).inlet)

    return {"pin": pin, "via": via, "re-attach": reattach, "add a unit": add}


@pytest.mark.parametrize(
    ("pumps", "index", "edit"),
    [
        *((1, 3, edit) for edit in _edits()),
        (1, 5, "add a unit"),
        (2, 3, "pin"),
    ],
)
def test_an_edit_after_reading_back_draws_as_on_the_original(
    pumps: int, index: int, edit: str
) -> None:
    """Check that an edit on a frozen-line sheet read back draws as on the sheet itself."""
    fs = _frozen(_bank(pumps), index)
    again = _read_back(fs)
    for sheet in (fs, again):
        _edits()[edit](sheet)
        sheet.route()

    assert _drawn(again) == _drawn(fs)


def test_a_frozen_line_on_a_sheet_with_an_angle_valve_draws_as_on_the_original() -> None:
    """Check that freezing a line on the stripped metering skid read back draws as on the sheet."""
    fs, _ = build_unpinned("06_metering_skid")
    fs.route()
    again = _read_back(fs)
    for sheet in (fs, again):
        _edits()["via"](sheet)
        sheet.route()

    assert _drawn(again) == _drawn(fs)


def test_a_spec_written_between_an_edit_and_route_routes_as_the_original() -> None:
    """Check that a spec written after via() and before route() routes as the sheet that wrote it."""
    fs = _bank(pumps=2)
    fs.route()
    _edits()["via"](fs)
    again = _read_back(fs)
    for sheet in (fs, again):
        sheet.route()

    assert _drawn(again) == _drawn(fs)


@pytest.mark.parametrize("change", ["add a unit", "remove a unit", "edit a description"])
def test_a_layout_drawn_for_another_spec_is_laid_out_afresh(change: str) -> None:
    """Check that a layout whose spec has changed is dropped and the sheet laid out afresh."""
    fs = _frozen(_bank(), 3)
    spec = fs.to_dict()
    if change == "add a unit":
        spec["units"].append({"kind": "Pump", "name": "P-9"})
    elif change == "remove a unit":
        spec["units"] = [u for u in spec["units"] if u["name"] != "P"]
        spec["streams"] = [s for s in spec["streams"] if s["to"][0] != "P"]
    else:
        spec["units"][0]["description"] = "Feed Splitter"
    fresh = {key: value for key, value in spec.items() if key != "layout"}
    drawn = _drawn(Flowsheet.from_dict(spec))

    assert drawn == _drawn(Flowsheet.from_dict(fresh))
    assert drawn != _drawn(fs)


@pytest.mark.parametrize(
    ("key", "value", "says"),
    [
        ("x", "left", "must be a number"),
        ("orientation", 45, "orientation must be 0, 90, 180 or 270"),
        ("port_faces", {"inlet": "Q"}, "names no port"),
        ("colour", "red", "unknown key 'colour'"),
    ],
)
def test_a_malformed_layout_entry_is_refused(key: str, value: Any, says: str) -> None:
    """Check that a bad value in the layout raises SpecError naming the entry."""
    fs = _bank()
    fs.route()
    spec = fs.to_dict()
    spec["layout"]["units"]["SP"][key] = value

    with pytest.raises(Exception, match=says) as excinfo:
        Flowsheet.from_dict(spec)
    assert "layout.units.SP" in str(excinfo.value)
