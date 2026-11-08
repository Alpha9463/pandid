"""Check locked and car-sealed valves: LO, LC, CSO and CSC, lettered where FC goes."""

import pytest

from _layout_cases import overlaps
from pandid import Flowsheet, spec, units as U
from pandid.render.drawio import DrawioRenderer
from pandid.render.svg import _unit_label_box, unit_tags
from pandid.render.symbols import default_registry
from test_drawio import _drawio_cells_from_document, _drawn_boxes

#: Each lock, and the position it holds the valve in.
_HELD = {"LO": "open", "LC": "closed", "CSO": "open", "CSC": "closed"}


def _on_a_line(valve: U.Valve, upright: bool = False) -> Flowsheet:
    """Return a laid-out sheet with ``valve`` in a line from a feed to a product."""
    fs = Flowsheet("locks")
    feed = fs.add(U.Feed("F")).pin(port="outlet", x=100, y=200)
    fs.add(valve).pin(port="inlet", x=250, y=200, orientation=90 if upright else 0)
    product = fs.add(U.Product("P")).pin(port="inlet", x=500, y=200)
    fs.connect(feed.outlet, valve.inlet)
    fs.connect(valve.outlet, product.inlet)
    fs.route()
    return fs


def _letters(fs: Flowsheet, valve: U.Valve) -> list[tuple]:
    """Return the label items the sheet writes for ``valve``, tag first."""
    return next(items for u, _tag, items in unit_tags(fs, None, "vertical") if u is valve)


@pytest.mark.parametrize("lock", sorted(_HELD))
def test_each_lock_is_lettered_below_a_horizontal_valve(lock):
    """Write LO, LC, CSO or CSC under the valve, past its tag, as FC is written."""
    valve = U.Valve("HV-1", lock=lock)
    fs = _on_a_line(valve)
    tag, letters = _letters(fs, valve)
    assert (letters[4], letters[5]) == ("bottom", lock)
    frame = valve.frame
    assert frame is not None
    box, tag_box = _unit_label_box(letters), _unit_label_box(tag)
    assert box is not None and tag_box is not None
    assert box[1] > frame.y + frame.h, "below the valve"
    assert not overlaps(box, tag_box), "clear of the tag"
    assert f">{lock}</text>" in fs.to_svg()


def test_a_lock_is_lettered_right_of_an_upright_valve():
    valve = U.Valve("HV-1", lock="CSO")
    fs = _on_a_line(valve, upright=True)
    letters = _letters(fs, valve)[-1]
    frame = valve.frame
    assert frame is not None
    assert (letters[4], letters[5]) == ("right", "CSO")
    assert letters[0] >= frame.x + frame.w


@pytest.mark.parametrize("lock", sorted(_HELD))
def test_draw_io_stacks_the_lock_under_the_tag(lock):
    fs = _on_a_line(U.Valve("HV-1", lock=lock))
    assert f'value="HV-1&lt;br&gt;{lock}"' in DrawioRenderer().render(fs)


@pytest.mark.parametrize("lock", sorted(_HELD))
def test_a_lock_holds_the_valve_in_its_position(lock):
    """Hold LO and CSO open, and LC and CSC closed with the gate's body darkened."""
    valve = U.Valve("HV-1", lock=lock)
    assert valve.normal_position == _HELD[lock]
    darkened = 'fill="#111"' in default_registry.for_unit(valve).svg
    assert darkened == (_HELD[lock] == "closed")


def test_a_lock_and_the_other_position_are_refused():
    with pytest.raises(ValueError, match="lock='LC' holds it closed"):
        U.Valve("HV-1", lock="LC", normal_position="open")
    valve = U.Valve("HV-2", lock="CSO")
    with pytest.raises(ValueError, match="normal_position is 'open', not 'closed'"):
        valve.normal_position = "closed"
    assert valve.normal_position == "open"


def test_a_locked_valve_has_no_fail_position():
    with pytest.raises(ValueError, match="has no fail position. Drop fail= or the lock"):
        U.Valve("XV-1", variant="solenoid", lock="LO", fail="closed")


def test_a_lock_that_is_not_one_names_the_four():
    with pytest.raises(ValueError, match="lock is one of 'LO', 'LC', 'CSO', 'CSC', got 'locked'"):
        U.Valve("HV-1", lock="locked")


@pytest.mark.parametrize("lock", sorted(_HELD))
def test_a_lock_round_trips_through_a_spec(lock):
    fs = Flowsheet("round trip")
    fs.add(U.Valve("HV-1", lock=lock))
    written = spec.to_dict(fs)
    assert written["units"][0]["lock"] == lock
    valve = Flowsheet.from_dict(written).units[0]
    assert isinstance(valve, U.Valve)
    assert (valve.lock, valve.normal_position) == (lock, _HELD[lock])
    assert spec.to_dict(Flowsheet.from_dict(written)) == written


@pytest.mark.parametrize("backwards", [False, True])
def test_a_row_of_locked_valves_keeps_every_tag_and_lock_off_the_others(backwards):
    """Keep the tags and their locks apart on close rows, on the sheet and in draw.io."""
    fs = Flowsheet("rows")
    rows = {
        200: [("HV-1000", 240, "CSO"), ("HV-11", 275, "LC"), ("HV-12", 310, "")],
        270: [("HV-20", 200, ""), ("HV-111", 250, "CSC"), ("HV-22", 295, "LO")],
    }
    for y, valves in rows.items():
        before = fs.add(U.Feed(f"F{y}")).pin(port="outlet", x=100, y=y).outlet
        for tag, x, lock in valves:
            valve = fs.add(U.Valve(tag, lock=lock)).pin(port="inlet", x=x, y=y)
            fs.connect(before, valve.inlet)
            before = valve.outlet
        fs.connect(before, fs.add(U.Product(f"P{y}")).pin(port="inlet", x=700, y=y).inlet)
    fs.route()
    if backwards:
        fs.units.reverse()
    halos = [
        box
        for _u, _tag, items in unit_tags(fs, None, "vertical")
        for box in map(_unit_label_box, items)
        if box is not None
    ]
    assert not [(a, b) for i, a in enumerate(halos) for b in halos[i + 1 :] if overlaps(a, b)]
    cells = _drawio_cells_from_document(fs.to_drawio(diagram="p&id"))
    _symbols, tags, _numbers = _drawn_boxes(fs, {"diagram": "p&id"}, cells)
    boxes = sorted(tags.items())
    assert not [
        (a, b)
        for i, (a, box) in enumerate(boxes)
        for b, other in boxes[i + 1 :]
        if overlaps(box, other)
    ]


@pytest.mark.parametrize("lock", ["LC", "CSC"])
def test_a_closed_lock_replaces_nc_on_a_body_that_is_not_darkened(lock):
    """Letter a closed butterfly with its lock alone, on the sheet and in draw.io."""
    fs = _on_a_line(U.Valve("HV-1", variant="butterfly", lock=lock))
    svg = fs.to_svg()
    assert f">{lock}</text>" in svg
    assert ">NC</text>" not in svg
    assert f'value="HV-1&lt;br&gt;{lock}"' in DrawioRenderer().render(fs)


def test_a_closed_lock_on_a_gate_keeps_the_darkened_body():
    valve = U.Valve("HV-1", lock="CSC")
    assert 'fill="#111"' in default_registry.for_unit(valve).svg
    assert ">NC</text>" not in _on_a_line(valve).to_svg()
