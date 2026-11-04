"""Check placement transforms: quarter turns, two-axis mirroring and moving a port's face."""

import math
import re

import pytest

from pandid import Flowsheet, units
from pandid.geometry import Pin, normalize_mirror, normalize_orientation
from pandid.portgeom import port_anchor, symbol_to_box


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
    assert normalize_mirror(True) == (True, False)  # bool shorthand = left/right
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


# --- what a second pin() call keeps ------------------------------------------


def test_a_second_pin_keeps_the_transform_the_first_asked_for():
    """Check that a later ``pin()`` that names no transform keeps the earlier one."""
    drum = units.Separator("V-1", variant="horizontal")
    drum.pin(x=100, y=100, orientation=90, mirrored="xy")
    drum.pin(y=200)
    assert (drum.pin_.x, drum.pin_.y) == (100.0, 200.0)
    assert (drum.pin_.orientation, drum.pin_.mirrored, drum.pin_.mirror_y) == (90, True, True)


def test_pin_still_clears_a_transform_when_asked_to():
    drum = units.Separator("V-1", variant="horizontal")
    drum.pin(x=100, y=100, orientation=90, mirrored=True)
    drum.pin(orientation=0, mirrored=False)
    assert (drum.pin_.orientation, drum.pin_.mirrored, drum.pin_.mirror_y) == (0, False, False)


def test_a_nudged_unit_is_still_drawn_turned():
    """Check that a nudged unit's turn reaches its drawn box and port faces."""
    fs, p = _pump_sheet(orientation=90)
    turned_box = (p.frame.w, p.frame.h)
    p.pin(y=260)
    fs.layout()
    assert p.frame.y == 260.0
    assert (p.frame.w, p.frame.h) == turned_box
    assert port_anchor(p, p.frame, "discharge")[2] == "S"


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
    """Check that ``nozzle()`` names faces as drawn on a mirrored unit."""
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
    # liquid draws off the bottom by gravity: the symbol authors one placement
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
    """Check that a face is judged against the new pin's transform, not the old frame's."""
    drum = units.Separator("V-1", variant="horizontal")
    _drum_sheet(drum)  # lays out, so drum.frame is resolved at orientation 0
    drum.pin(x=200, y=100, orientation=90)
    with pytest.raises(ValueError, match="you asked for 'W'"):
        drum.nozzle("feed", "W")


def test_an_unreachable_face_raises_at_resolve_time_rather_than_falling_back():
    """Check that resolving a face the frame's transform cannot reach raises."""
    from pandid.portgeom import resolve_port

    drum = units.Separator("V-1", variant="horizontal")
    _drum_sheet(drum)
    drum.nozzle("feed", "W")
    assert resolve_port(drum, drum.frame, "feed").face == "W"

    drum.frame.orientation = 90
    with pytest.raises(ValueError, match="you asked for 'W'"):
        resolve_port(drum, drum.frame, "feed")


def test_pin_leaves_the_transform_alone_when_it_rejects_the_placement():
    """Check that a refused ``pin()`` leaves the unit's transform unchanged."""
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


def test_nozzle_records_the_face_as_drawn():
    drum = units.Separator("V-1", variant="horizontal")
    drum.nozzle("feed", "N")
    assert drum._port_faces == {"feed_1": "N"}


def test_an_unanchored_port_reports_the_face_it_actually_resolves_to(gapped_kind):
    """Check that ``port_faces`` reports the face an unanchored port resolves to."""
    from pandid.portgeom import port_faces, resolve_port

    fs = Flowsheet("gapped")
    unit = fs.add(gapped_kind("G-1")).pin(x=100, y=100)
    fs.layout()

    resolved = resolve_port(unit, unit.frame, "spare_a")
    assert port_faces(unit, "spare_a") == [resolved.face]
    unit.nozzle("spare_a", resolved.face)  # the face it is already on
    with pytest.raises(ValueError, match=r"can be piped from N as drawn"):
        unit.nozzle("spare_a", "S")


def test_a_series_port_survives_a_quarter_turn(gapped_kind):
    """Check that a quarter turn moves a mixer's rule-placed inlets with its box."""
    from pandid.portgeom import port_faces

    fs = Flowsheet("turned-mixer")
    mix = fs.add(units.Mixer("M-1", n_inlets=3)).pin(x=100, y=100, orientation=90)
    fs.layout()

    # The inlets are on the triangle's flat back; a clockwise quarter turn puts
    # that face up, and mirroring puts it back down.
    assert [port_faces(mix, f"in_{i}") for i in (1, 2, 3)] == [["N"]] * 3
    assert port_faces(mix, "in_2", Pin(x=0, y=0, orientation=90, mirrored=True)) == ["S"]


# A symbol's own lettering under a placement transform.


def _linear(transform: str) -> tuple[float, float, float, float]:
    """Linear part (a, b, c, d) of an SVG transform list, applied right-to-left."""
    a, b, c, d = 1.0, 0.0, 0.0, 1.0
    ops = re.findall(r"(translate|scale|rotate)\(([^)]*)\)", transform)
    for name, raw in reversed(ops):
        args = [float(v) for v in re.split(r"[,\s]+", raw.strip()) if v]
        if name == "translate":
            continue  # no contribution to the linear part
        if name == "scale":
            sx = args[0]
            sy = args[1] if len(args) > 1 else sx
            m = (sx, 0.0, 0.0, sy)
        else:
            t = math.radians(args[0])
            m = (math.cos(t), math.sin(t), -math.sin(t), math.cos(t))
        # this op is applied before those accumulated so far: (a,b,c,d) . m
        a, b, c, d = (
            a * m[0] + c * m[1],
            b * m[0] + d * m[1],
            a * m[2] + c * m[3],
            b * m[2] + d * m[3],
        )
    return a, b, c, d


@pytest.mark.parametrize(
    "rot,mirror",
    [
        (0, False),
        (90, False),
        (180, False),
        (270, False),
        (0, "x"),
        (0, "y"),
        (90, "y"),
        (180, "x"),
    ],
)
def test_a_symbols_own_lettering_stays_upright(rot, mirror):
    """Check that a placed valve's operator letter is drawn upright."""
    fs = Flowsheet("lettering")
    fs.add(units.Valve("FV-1", variant="motor")).pin(x=200, y=200, orientation=rot, mirrored=mirror)
    fs.layout()
    svg = fs.to_svg(check=False)

    use = re.search(r'<use href="#(sym_valve_motor[^"]*)"[^>]*?(?:transform="([^"]*)")?\s*/>', svg)
    assert use, "no <use> for the valve"
    body = re.search(rf'<symbol id="{use.group(1)}".*?</symbol>', svg, re.S)
    assert body, f"no <symbol> defining {use.group(1)}"
    wrapped = re.findall(r'<g transform="([^"]*)"><text', body.group(0))
    assert wrapped or (not rot and not mirror), "lettering was left un-counter-transformed"

    for inner in wrapped or [""]:
        a, b, c, d = _linear(" ".join([use.group(2) or "", inner]))
        # Upright and unreflected: no rotation or skew, and no negative scale.
        assert abs(b) < 1e-9 and abs(c) < 1e-9, f"glyph is rotated: {(a, b, c, d)}"
        assert a > 0 and d > 0, f"glyph is mirrored: {(a, b, c, d)}"


def test_lettered_symbols_get_one_definition_per_transform():
    """Check that lettered symbols get one definition per transform; others share one."""
    fs = Flowsheet("defs")
    fs.add(units.Valve("FV-1", variant="motor")).pin(x=100, y=100)
    fs.add(units.Valve("FV-2", variant="motor")).pin(x=300, y=100, mirrored="y")
    fs.add(units.Valve("HV-1", variant="control")).pin(x=500, y=100)
    fs.add(units.Valve("HV-2", variant="control")).pin(x=700, y=100, mirrored="y")
    fs.layout()
    svg = fs.to_svg(check=False)

    assert sorted(set(re.findall(r'<symbol id="(sym_valve_motor[^"]*)"', svg))) == [
        "sym_valve_motor",
        "sym_valve_motor_ty",
    ]
    assert re.findall(r'<symbol id="(sym_valve_control[^"]*)"', svg) == ["sym_valve_control"]


# A symbol's own direction under every placement transform: a mirror or
# orientation=180 is undone, orientation=90 or 270 is carried.

#: (0, 80) -> (80, 0) as the cooler stencil draws it: up and to the right on a
#: y-down canvas. Read as a direction, so the length does not matter.
_DUTY_HEADING = (1.0, -1.0)
#: The heater's own, which is the same diagonal walked the other way -- the
#: whole of the difference between the two drawings.
_HEATER_HEADING = (-1.0, 1.0)


def _unit_vector(dx: float, dy: float) -> tuple[float, float]:
    scale = math.hypot(dx, dy)
    return (dx / scale, dy / scale)


def _turned(dx: float, dy: float, degrees: float) -> tuple[float, float]:
    """Return a direction turned clockwise on a y-down canvas."""
    t = math.radians(degrees)
    return _unit_vector(dx * math.cos(t) - dy * math.sin(t), dx * math.sin(t) + dy * math.cos(t))


def _drawn_heading(svg: str, sym_id_prefix: str, dx: float, dy: float):
    """Return a symbol-space direction as the sheet draws it."""
    use = re.search(rf'<use href="#({sym_id_prefix}[^"]*)"[^>]*?(?:transform="([^"]*)")?\s*/>', svg)
    assert use, f"no <use> for {sym_id_prefix}"
    body = re.search(rf'<symbol id="{use.group(1)}".*?</symbol>', svg, re.S)
    assert body, f"no <symbol> defining {use.group(1)}"
    baked = re.search(r'<g transform="([^"]*)">', body.group(0))
    a, b, c, d = _linear(" ".join([use.group(2) or "", baked.group(1) if baked else ""]))
    return _unit_vector(a * dx + c * dy, b * dx + d * dy)


@pytest.mark.parametrize("rot", [0, 90, 180, 270])
@pytest.mark.parametrize("mirror", [False, "x", "y", "xy"])
def test_a_directional_symbols_arrow_survives_every_placement(rot, mirror):
    """Check that the duty arrow is never drawn reversed at any of the eight placements."""
    fs = Flowsheet("duty")
    fs.add(units.Cooler("E-1")).pin(x=200, y=200, orientation=rot, mirrored=mirror)
    fs.layout()
    got = _drawn_heading(fs.to_svg(check=False), "sym_cooler", *_DUTY_HEADING)
    # 180 is a reflection pair, not a turn: only a quarter turn is carried.
    assert got == pytest.approx(_turned(*_DUTY_HEADING, 0 if rot in (0, 180) else rot))


def test_a_quarter_turned_cooler_is_not_the_heater_turned_the_other_way():
    """Check that a quarter-turned cooler's arrow is off the heater's diagonal."""
    fs = Flowsheet("turned")
    fs.add(units.Cooler("E-1")).pin(x=200, y=200, orientation=90)
    fs.add(units.Heater("E-2")).pin(x=600, y=200)
    fs.layout()
    svg = fs.to_svg(check=False)
    cooler = _drawn_heading(svg, "sym_cooler", *_DUTY_HEADING)
    heater = _drawn_heading(svg, "sym_heater", *_HEATER_HEADING)
    # The heater walks the same diagonal the other way, which is the whole of
    # what makes it the other symbol -- and is what a half turn would have
    # turned the cooler into.
    assert heater == pytest.approx(_turned(*_DUTY_HEADING, 180))
    # The quarter-turned cooler is on neither end of that diagonal: the cross
    # product with it is 1 for a perpendicular direction and 0 for a parallel
    # one, either way round.
    assert abs(cooler[0] * heater[1] - cooler[1] * heater[0]) > 0.5


def test_a_flipped_directional_symbol_still_moves_its_nozzles():
    """Check that flipping a directional symbol still moves its nozzles."""
    from pandid.portgeom import port_point

    fs = Flowsheet("nozzles")
    upright = fs.add(units.Cooler("E-1")).pin(x=200, y=200)
    flipped = fs.add(units.Cooler("E-2")).pin(x=500, y=200, mirrored="y")
    turned = fs.add(units.Cooler("E-3")).pin(x=800, y=200, orientation=180)
    fs.layout()
    # utility_out is drawn on the crown; flipped or turned over, it is underneath.
    assert port_point(upright, upright.frame, "utility_out")[1] < upright.frame.cy
    assert port_point(flipped, flipped.frame, "utility_out")[1] > flipped.frame.cy
    assert port_point(turned, turned.frame, "utility_out")[1] > turned.frame.cy


def test_a_directional_symbol_takes_one_definition_per_reflection():
    """Check that a directional symbol takes four definitions, one per reflection."""
    fs = Flowsheet("defs")
    for i, rot in enumerate((0, 90, 180, 270)):
        for j, mirror in enumerate((False, "x", "y", "xy")):
            fs.add(units.Cooler(f"E-{i}{j}")).pin(
                x=200 + 220 * i, y=200 + 220 * j, orientation=rot, mirrored=mirror
            )
    fs.layout()
    svg = fs.to_svg(check=False)
    assert sorted(set(re.findall(r'<symbol id="(sym_cooler[^"]*)"', svg))) == [
        "sym_cooler",
        "sym_cooler_tx",
        "sym_cooler_txy",
        "sym_cooler_ty",
    ]
