"""Check that route() closes the empty bands across a drawing."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from pandid import Flowsheet, units as U
from pandid.devices import ControlValve
from pandid.document import TableBox, notes
from pandid.layout.attach import stream_path
from pandid.layout.compact import covered, empty_bands
from pandid.layout.conflicts import boxes_overlap, segment_crosses_box
from pandid.portgeom import port_point, unit_box
from pandid.render.furniture import measure_annotation, measure_table
from pandid.render.svg import _unit_label_box, sheet_connections, stream_numbers, unit_tags
from pandid.route_geometry import stream_polyline
from pandid.routing.lanes import _score
from _layout_cases import build_unpinned, frame_of

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
    """Return which way each run of each drawn line heads."""
    return [
        [(bx > ax, bx < ax, by > ay, by < ay) for (ax, ay), (bx, by) in zip(path, path[1:])]
        for path in map(stream_polyline, fs.streams)
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


def _codes(fs: Flowsheet) -> set[str]:
    """Return the codes validate() finds."""
    return {i.code for i in fs.validate()}


def _unit(fs: Flowsheet, name: str) -> U.Unit:
    """Return the unit with a name."""
    return next(u for u in fs.units if u.name == name)


def test_a_line_routed_by_hand_on_the_closed_sheet_keeps_its_ends() -> None:
    """Check that via() points read off the closed sheet join the units drawn there."""
    fs = _chain()
    fs.route()
    before = _boxes(fs)
    line = fs.streams[1]
    (a, y), (b, _) = stream_polyline(line)
    line.via([(a + 30, y), (a + 30, y - 100), (b - 30, y - 100), (b - 30, y)])
    fs.route()

    assert _boxes(fs) == before
    assert "route-crosses-unit" not in _codes(fs)


def test_a_line_routed_by_hand_between_units_pinned_on_the_closed_sheet_keeps_its_ends() -> None:
    """Check that a via() and pins on both sides of the closed band, read off the sheet, agree."""
    fs = _chain()
    fs.route()
    before = _boxes(fs)
    line = fs.streams[1]
    (a, y), (b, _) = stream_polyline(line)
    line.via([(a + 30, y), (a + 30, y - 100), (b - 30, y - 100), (b - 30, y)])
    for name in ("V-101", "V-102"):
        unit = _unit(fs, name)
        unit.pin(x=frame_of(unit).x, y=frame_of(unit).y)
    fs.route()

    assert _boxes(fs) == before
    assert "route-crosses-unit" not in _codes(fs)


@pytest.mark.parametrize("name", ["V-101", "P-101", "V-102", "LT-101", "LIC-101", "suction"])
def test_a_pin_where_the_closed_sheet_draws_a_unit_moves_nothing(name: str) -> None:
    """Check that pinning one unit or nozzle where the closed sheet draws it changes nothing."""
    fs = _chain()
    fs.route()
    before = _boxes(fs)
    if name == "suction":
        pump = _unit(fs, "P-101")
        x, y = port_point(pump, frame_of(pump), name)
        pump.pin(port=name, x=x, y=y)
    else:
        unit = _unit(fs, name)
        unit.pin(x=frame_of(unit).x, y=frame_of(unit).y)
    fs.route()

    assert _boxes(fs) == before


#: A note's lines.
NOTE = ["Drain"]


def _note_box(fs: Flowsheet, x: float, y: float) -> Box:
    """Add the note with its corner at a point and return its box."""
    w, h = measure_annotation(fs.add_annotation(notes(NOTE, position=(x, y))))
    return (x, y, x + w, y + h)


def _clear(a: Box, b: Box) -> bool:
    """Return whether two boxes do not overlap."""
    return a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]


def test_closing_a_band_keeps_equipment_off_a_placed_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Check that a note placed in the band keeps the pump from closing onto it."""
    pump = _boxes(_open_chain(monkeypatch))["P-101"]
    width, _ = measure_annotation(notes(NOTE))
    fs = _chain()
    note = _note_box(fs, pump[0] - width - 10.0, pump[1])
    fs.route()

    assert all(_clear(box, note) for box in _boxes(fs).values())


def test_closing_a_band_slides_no_unit_under_a_placed_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Check that a note placed past the band keeps the drum moving in from sliding under it."""
    drum = _boxes(_open_chain(monkeypatch))["V-102"]
    width, _ = measure_annotation(notes(NOTE))
    fs = _chain()
    note = _note_box(fs, drum[0] - width - 10.0, drum[1])
    fs.route()

    assert all(_clear(box, note) for box in _boxes(fs).values())


def test_a_line_routed_by_hand_on_the_closed_sheet_keeps_its_ends_when_read_back() -> None:
    """Check that the sheet read back from its spec draws a via() read off the closed sheet the same."""
    fs = _chain()
    fs.route()
    line = fs.streams[1]
    (a, y), (b, _) = stream_polyline(line)
    line.via([(a + 30, y), (a + 30, y - 100), (b - 30, y - 100), (b - 30, y)])
    fs.route()
    again = Flowsheet.from_dict(fs.to_dict())
    again.route()

    assert _boxes(again) == _boxes(fs)
    assert "route-crosses-unit" not in _codes(again)


def test_a_note_placed_on_the_closed_sheet_keeps_its_room() -> None:
    """Check that a note placed beside a unit the closed sheet draws stays clear of it."""
    fs = _chain()
    fs.route()
    before = _boxes(fs)
    drum = before["V-102"]
    note = _note_box(fs, drum[2] + 10.0, drum[1])
    fs.route()

    assert _boxes(fs) == before
    assert all(_clear(box, note) for box in _boxes(fs).values())


def test_lines_routed_by_hand_as_a_closed_sheet_draws_them_move_nothing() -> None:
    """Check that via() on each line where a closed sheet with hung balloons draws it moves no unit."""
    fs, _ = build_unpinned("14_condensing_turbine")
    fs.route()
    before = _boxes(fs)
    for line in fs.streams:
        line.via(stream_polyline(line)[1:-1])
    fs.route()

    after = _boxes(fs)
    assert [k for k in before if after[k] != pytest.approx(before[k], abs=0.01)] == []


def test_closing_a_band_draws_no_tag_over_a_placed_note() -> None:
    """Check that a pump's tag does not move in under a note placed above where it was."""
    fs = _chain()
    note = _note_box(fs, 390.0, 119.0)
    fs.to_svg(diagram="p&id")

    joints = sheet_connections("p&id", None)
    tags = [
        _unit_label_box(item) for _, _, items in unit_tags(fs, joints, "vertical") for item in items
    ]
    assert not any(box is not None and boxes_overlap(box, note) for box in tags)


def _valved() -> Flowsheet:
    """Return the chain with a control valve, failing closed, before the second drum."""
    fs = Flowsheet("valved")
    drum = fs.add(U.Vessel("V-101"))
    pump = fs.add(U.Pump("P-101"))
    fs.connect(drum.outlet, pump.suction)
    valve = fs.add(ControlValve("CV-101", fail="closed"))
    fs.connect(pump.discharge, valve.inlet)
    fs.connect(valve.outlet, fs.add(U.Vessel("V-102")).inlet)
    return fs


def _packaged() -> Flowsheet:
    """Return the chain with its pump in a package."""
    fs = _chain()
    fs.package("PK-101", [_unit(fs, "P-101")])
    return fs


def _labels(fs: Flowsheet) -> dict[str, Box]:
    """Return the drawn box of the pump's tag, the valve's letters and a line number."""
    out: dict[str, Box] = {}
    placed: list[Box] = []
    for unit, tag, items in unit_tags(fs, None, "vertical"):
        for item in items:
            box = _unit_label_box(item)
            if box is not None:
                placed.append(box)
                out[f"{unit.name} {'tag' if item is tag else 'letters'}"] = box
    numbers = stream_numbers(fs, placed, None, "vertical")
    out["number"] = next(n.words for n in numbers if n.words is not None)
    return out


def _touches_only_labels(fs: Flowsheet, box: Box) -> bool:
    """Return whether no unit or line run meets a box."""
    runs = [(a, b) for path in map(stream_path, fs.streams) for a, b in zip(path, path[1:])]
    return not any(boxes_overlap(unit_box(u, frame_of(u)), box) for u in fs.units) and not any(
        segment_crosses_box(a, b, box) for a, b in runs
    )


@pytest.mark.parametrize(
    ("make", "label", "side"),
    [
        (_chain, "P-101 tag", "above"),
        (_valved, "CV-101 letters", "below"),
        (_chain, "number", "above"),
    ],
    ids=["tag", "fail-letters", "line-number"],
)
def test_a_label_drawn_over_a_placed_note_counts(
    make: Callable[[], Flowsheet], label: str, side: str
) -> None:
    """Check that the closing's keep check counts a label, and nothing else, over a placed note."""
    fs = make()
    fs.route()
    x0, y0, x1, y1 = _labels(fs)[label]
    w, h = measure_annotation(notes(NOTE))
    y = y0 + 3.0 - h if side == "above" else y1 - 3.0
    note = _note_box(fs, (x0 + x1 - w) / 2, y)

    assert _touches_only_labels(fs, note)
    assert covered(fs)


def test_the_judged_counts_name_each_thing_drawn_over_a_placed_note() -> None:
    """Check that the counts every redraw is judged by hold one per thing over a note, by name."""
    from pandid.layout.control import _flaws

    fs = _chain()
    fs.route()
    x0, y0, x1, _ = _labels(fs)["P-101 tag"]
    w, h = measure_annotation(notes(NOTE))
    _note_box(fs, (x0 + x1 - w) / 2, y0 + 3.0 - h)

    over = {k: n for k, n in _flaws(fs).items() if k.startswith("covered ")}
    assert over == {f"covered {kind} {key}": 1 for kind, key in covered(fs)}
    assert "covered label ('P-101', 0)" in over


def test_a_package_label_drawn_over_a_placed_note_counts() -> None:
    """Check that the keep check counts a package's tag over a placed note."""
    from pandid.package import frame as package_frame
    from pandid.render.svg import package_labels

    fs = _packaged()
    fs.route()
    package = fs.packages[0]
    frame = package_frame(package)
    assert frame is not None
    x0, y0, x1, _ = next(
        b for b in map(_unit_label_box, package_labels(package, frame)) if b is not None
    )
    w, h = measure_annotation(notes(NOTE))
    note = _note_box(fs, (x0 + x1 - w) / 2, y0 + 3.0 - h)

    assert _touches_only_labels(fs, note)
    assert covered(fs)


def test_a_tag_drawn_over_a_placed_table_counts() -> None:
    """Check that the keep check counts a tag over a table placed by position."""
    fs = _chain()
    fs.route()
    x0, y0, x1, _ = _labels(fs)["P-101 tag"]
    table = TableBox(title="DUTY", headers=["Unit", "kW"], rows=[["P-101", "15"]])
    w, h = measure_table(table)
    table.position = ((x0 + x1 - w) / 2, y0 + 3.0 - h)
    fs.add_annotation(table)
    box = (table.position[0], table.position[1], table.position[0] + w, table.position[1] + h)

    assert _touches_only_labels(fs, box)
    assert covered(fs)


@pytest.mark.parametrize(
    ("stem", "stripped"),
    [("03_control_loop", False), ("03_control_loop", True), ("07_from_data", True)],
    ids=["03-as-written", "03-stripped", "07-stripped"],
)
def test_route_draws_every_unit_on_the_sheet(stem: str, stripped: bool) -> None:
    """Check that no unit is drawn at a negative coordinate, and that each pins where drawn."""
    from _render_cases import gallery

    fs, _ = build_unpinned(stem) if stripped else gallery.flowsheet(stem)
    fs.route()
    before = _boxes(fs)
    assert [u.name for u in fs.units if frame_of(u).x < 0 or frame_of(u).y < 0] == []

    for unit in fs.units:
        unit.pin(x=frame_of(unit).x, y=frame_of(unit).y, port=None)
    fs.route()

    assert [i.code for i in fs.validate() if i.severity == "error"] == []
    assert _boxes(fs) == before


def _gauged() -> Flowsheet:
    """Return the chain with a pressure gauge on the pump, past the band layout leaves."""
    fs = _chain()
    fs.add_instrument("PI", 102, sensing=_unit(fs, "P-101"), face="N")
    return fs


def test_a_balloon_pinned_where_the_closed_sheet_draws_it_moves_nothing() -> None:
    """Check that pinning a balloon past a closed band where drawn keeps the band closed."""
    fs = _gauged()
    fs.route()
    before = _boxes(fs)
    gauge = _unit(fs, "PI-102")
    gauge.pin(x=frame_of(gauge).x, y=frame_of(gauge).y)
    for _ in range(2):
        fs.route()

        assert _boxes(fs) == before
    assert [i.code for i in fs.validate() if i.severity == "error"] == []


@pytest.mark.parametrize("stated", [{"orientation": 0}, {"mirrored": False}])
def test_a_pin_where_drawn_that_restates_the_turn_is_no_edit(stated: dict[str, Any]) -> None:
    """Check that a pin where drawn restating the drawn turn or mirror leaves the sheet unchanged."""
    fs = _gauged()
    fs.route()
    pump = _unit(fs, "P-101")
    pump.pin(x=frame_of(pump).x, y=frame_of(pump).y, **stated)

    assert fs._given() == fs._given_then


@pytest.mark.parametrize(
    ("stem", "name"), [("06_metering_skid", "FI-101"), ("08_line_numbers", "HV-101")]
)
def test_a_unit_pinned_where_drawn_moves_nothing_on_later_routes(stem: str, name: str) -> None:
    """Check that one unit pinned where drawn leaves every unit where it was over two routes."""
    fs, _ = build_unpinned(stem)
    fs.route()
    before = _boxes(fs)
    unit = _unit(fs, name)
    unit.pin(x=frame_of(unit).x, y=frame_of(unit).y)
    for _ in range(2):
        fs.route()

        assert _boxes(fs) == before


def _vessel_at_the_top(face: str, count: int, note: tuple[float, float] | None = None) -> Flowsheet:
    """Return a vessel pinned at the sheet's top edge with balloons on one face, and a note."""
    fs = Flowsheet("vessel")
    if note is not None:
        fs.add_annotation(notes(["CAUTION"], position=note))
    vessel = fs.add(U.Vessel("V-101").pin(x=300, y=0))
    pump = fs.add(U.Pump("P-101"))
    fs.connect(fs.add(U.Feed("Feed")).outlet, vessel.inlet)
    fs.connect(vessel.outlet, pump.suction)
    fs.connect(pump.discharge, fs.add(U.Product("Product")).inlet)
    for k in range(count):
        fs.add_instrument(["PI", "TI", "LI", "AI"][k], 101 + k, sensing=vessel, face=face)
    fs.route()
    return fs


def test_a_balloon_kept_on_the_sheet_draws_no_tap_through_another() -> None:
    """Check that a balloon moved on the sheet shares no tap and draws none through a balloon."""
    from pandid.layout.control import _flaws

    fs = _vessel_at_the_top("E", 2)
    flaws = _flaws(fs)

    assert (flaws["tap-through-unit"], flaws["line-on-line"]) == (0, 0)
    assert [u.name for u in fs.units if frame_of(u).y < 0] == []
    assert fs.to_svg(diagram="p&id")


def test_a_balloon_left_off_the_sheet_is_reported_and_draws() -> None:
    """Check that a balloon no clear spot on the sheet takes is reported, and the sheet draws."""
    fs = _vessel_at_the_top("W", 4)
    off = sorted(u.name for u in fs.units if frame_of(u).y < 0)

    assert off == ["AI-104", "LI-103"]
    assert sorted(i.message.split()[0] for i in fs.validate() if i.code == "unit-off-sheet") == off
    assert [i.code for i in fs.validate() if i.severity == "error"] == []
    assert fs.to_svg(diagram="p&id")


def test_a_balloon_kept_on_the_sheet_keeps_off_a_placed_note() -> None:
    """Check that a balloon moved on the sheet is not drawn over a note placed there."""
    fs = _vessel_at_the_top("E", 2, note=(435.0, 12.0))
    fs.to_svg(diagram="p&id")

    assert covered(fs) == set()
