"""Placement transforms: quarter-turn rotation, two-axis mirroring, and moving a
port to another face of its symbol."""

import pytest

from pfd import Flowsheet, units
from pfd.geometry import normalize_mirror, normalize_orientation
from pfd.portgeom import port_anchor, symbol_to_box


def _pump_sheet(**pin_kwargs):
    fs = Flowsheet("T")
    a = fs.add(units.Feed("in")).pin(x=40, y=150)
    p = fs.add(units.Pump("P-1")).pin(x=220, y=140, **pin_kwargs)
    b = fs.add(units.Product("out")).pin(x=420, y=150)
    fs.connect(a.outlet, p.suction)
    fs.connect(p.discharge, b.inlet)
    fs.layout()
    fs.route()
    return fs, p


# --- normalisation -----------------------------------------------------------


def test_orientation_accepts_quarter_turns_only():
    assert normalize_orientation(0) == 0
    assert normalize_orientation(90) == 90
    assert normalize_orientation(-90) == 270
    assert normalize_orientation(450) == 90
    with pytest.raises(ValueError):
        normalize_orientation(45)


def test_mirror_spec_covers_both_axes():
    assert normalize_mirror(False) == (False, False)
    assert normalize_mirror(True) == (True, False)  # historical bool = left/right
    assert normalize_mirror("x") == (True, False)
    assert normalize_mirror("vertical") == (False, True)
    assert normalize_mirror("xy") == (True, True)
    with pytest.raises(ValueError):
        normalize_mirror("sideways")


# --- the symbol -> box mapping ----------------------------------------------


def test_symbol_to_box_quarter_turns_swap_the_box():
    # top-left corner of a 100x50 symbol, rotated clockwise
    assert symbol_to_box(0, 0, 100, 50, 0) == (0, 0, 100, 50)
    assert symbol_to_box(0, 0, 100, 50, 90) == (50, 0, 50, 100)  # -> top-right
    assert symbol_to_box(0, 0, 100, 50, 180) == (100, 50, 100, 50)  # -> bottom-right
    assert symbol_to_box(0, 0, 100, 50, 270) == (0, 100, 50, 100)  # -> bottom-left


def test_symbol_to_box_mirrors_before_rotating():
    # mirroring x then rotating 90 must not equal rotating then mirroring
    assert symbol_to_box(10, 0, 100, 50, 90, True) == (50, 90, 50, 100)
    assert symbol_to_box(10, 0, 100, 50, 0, False, True) == (10, 50, 100, 50)


# --- rotation reaches layout and routing ------------------------------------


def test_quarter_turn_swaps_the_resolved_box():
    _, upright = _pump_sheet()
    _, turned = _pump_sheet(orientation=90)
    assert (turned.frame.w, turned.frame.h) == (upright.frame.h, upright.frame.w)


@pytest.mark.parametrize(
    "kw",
    [
        {},
        {"orientation": 90},
        {"orientation": 180},
        {"orientation": 270},
        {"mirrored": "x"},
        {"mirrored": "y"},
        {"mirrored": "xy"},
        {"orientation": 90, "mirrored": "y"},
    ],
)
def test_ports_stay_on_the_unit_under_every_transform(kw):
    # The whole point of routing through portgeom: however the symbol is placed,
    # its anchors stay on the frame's boundary, so streams cannot detach.
    _, p = _pump_sheet(**kw)
    f = p.frame
    for name in ("suction", "discharge"):
        ax, ay, d = port_anchor(p, f, name)
        assert f.x - 0.5 <= ax <= f.x + f.w + 0.5, f"{name} x off the frame ({kw})"
        assert f.y - 0.5 <= ay <= f.y + f.h + 0.5, f"{name} y off the frame ({kw})"
        assert d in ("N", "S", "E", "W")


def test_rotation_moves_the_face_a_port_leaves_from():
    _, upright = _pump_sheet()
    _, turned = _pump_sheet(orientation=90)
    assert port_anchor(upright, upright.frame, "discharge")[2] == "E"
    assert port_anchor(turned, turned.frame, "discharge")[2] == "S"


# --- moving a port to another face ------------------------------------------


def _drum_sheet(drum, **pin_kwargs):
    fs = Flowsheet("D")
    fs.add(drum).pin(x=200, y=100, **pin_kwargs)
    fs.add(units.Feed("f")).pin(x=20, y=100)
    fs.connect(fs.units[1].outlet, drum.feed)
    fs.layout()
    return fs


def test_nozzle_moves_the_connection():
    drum = units.Separator("V-1", variant="horizontal")
    fs = _drum_sheet(drum)
    assert port_anchor(drum, drum.frame, "feed")[2] == "W"

    drum.nozzle("feed", "N")
    fs.layout()
    assert port_anchor(drum, drum.frame, "feed")[2] == "N"


def test_nozzle_accepts_the_label_pos_side_names():
    drum = units.Separator("V-1", variant="horizontal")
    fs = _drum_sheet(drum)
    drum.nozzle("feed", "top")
    fs.layout()
    assert port_anchor(drum, drum.frame, "feed")[2] == "N"


def test_nozzle_names_the_face_as_drawn_not_as_authored():
    """#26: the drum's alternate is authored on the symbol's north head, so on a
    top-to-bottom mirrored unit that placement is drawn on the SOUTH. Naming the
    face in drawn space is what stops "N" quietly putting the nozzle below."""
    drum = units.Separator("V-1", variant="horizontal")
    fs = _drum_sheet(drum, mirrored="y")
    with pytest.raises(ValueError, match="you asked for 'N'"):
        drum.nozzle("feed", "N")

    drum.nozzle("feed", "S")
    fs.layout()
    assert port_anchor(drum, drum.frame, "feed") == (220.0, 130.0, "S")


def test_nozzle_rejects_unknown_port_and_fixed_nozzle():
    drum = units.Separator("V-1", variant="horizontal")
    with pytest.raises(KeyError):
        drum.nozzle("nope", "N")
    # liquid draws off the bottom by gravity — the symbol authors one placement
    with pytest.raises(ValueError, match=r"V-1\.liquid can be piped from S as drawn"):
        drum.nozzle("liquid", "N")


def test_pin_rechecks_a_face_the_new_transform_can_no_longer_reach():
    # A quarter turn takes the drum's three drawn faces from W/N/E to N/E/S, so
    # a west nozzle chosen beforehand has nowhere to land and must say so.
    drum = units.Separator("V-1", variant="horizontal")
    drum.nozzle("feed", "W")
    with pytest.raises(ValueError, match="you asked for 'W'"):
        drum.pin(x=200, y=100, orientation=90)


def test_a_face_is_named_against_the_pin_not_the_frame_it_replaces():
    """#38/D2: port_faces() preferred the resolved frame, so once a layout had
    run a pin() answered from the transform it was in the act of replacing --
    and the accepted face then fell back to the home nozzle at resolve time.
    This is the order the docs recommend: pin, then nozzle."""
    drum = units.Separator("V-1", variant="horizontal")
    _drum_sheet(drum)  # lays out, so drum.frame is resolved at orientation 0
    drum.pin(x=200, y=100, orientation=90)
    with pytest.raises(ValueError, match="you asked for 'W'"):
        drum.nozzle("feed", "W")


def test_an_unreachable_face_raises_at_resolve_time_rather_than_falling_back():
    """#38/D2: the guard that matters is the one in the resolver. Every check
    upstream of it can be outrun by a later change of transform -- a frame
    another engine wrote, here -- and it is the resolver that decides where the
    ink goes, so a fall-back to the home nozzle there is silent by definition."""
    from pfd.portgeom import resolve_port

    drum = units.Separator("V-1", variant="horizontal")
    _drum_sheet(drum)
    drum.nozzle("feed", "W")
    assert resolve_port(drum, drum.frame, "feed").face == "W"

    drum.frame.orientation = 90
    with pytest.raises(ValueError, match="you asked for 'W'"):
        resolve_port(drum, drum.frame, "feed")


def test_pin_leaves_the_transform_alone_when_it_rejects_the_placement():
    """#38/D3: pin() committed the new transform and only then re-checked, so
    catching the error left the unit in the state the check exists to prevent."""
    drum = units.Separator("V-1", variant="horizontal")
    drum.pin(x=200, y=100)
    drum.nozzle("feed", "W")
    with pytest.raises(ValueError):
        drum.pin(x=640, y=480, orientation=90)
    assert (drum.pin_.x, drum.pin_.y) == (200.0, 100.0)
    assert (drum.pin_.orientation, drum.pin_.mirrored, drum.pin_.mirror_y) == (0, False, False)
    fs = Flowsheet("still-valid")
    fs.add(drum)
    fs.layout()
    assert port_anchor(drum, drum.frame, "feed")[2] == "W"


def test_port_face_still_works_and_warns():
    drum = units.Separator("V-1", variant="horizontal")
    with pytest.deprecated_call():
        drum.port_face("feed", "N")
    assert drum._port_faces == {"feed": "N"}
