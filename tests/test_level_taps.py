"""Check two-tap level instruments and the marks drawn at a balloon's tap end."""

import math
import re
import xml.etree.ElementTree as ET

import pytest

from pandid import Flowsheet, units


def _taps_group(svg: str) -> str:
    """Return the body of the sheet's tap-line group."""
    return svg.split('<g id="instrument_taps">', 1)[1].split("</g>", 1)[0]


def _polylines(body: str) -> list[list[tuple[float, float]]]:
    """Return every ``<line>`` and every ``M``/``L`` ``<path>`` in a group as points."""
    out = []
    for x1, y1, x2, y2 in re.findall(
        r'<line x1="([-\d.]+)" y1="([-\d.]+)" x2="([-\d.]+)" y2="([-\d.]+)"', body
    ):
        out.append([(float(x1), float(y1)), (float(x2), float(y2))])
    for d in re.findall(r'<path d="(M [^"]+)"', body):
        if "A" in d:
            continue
        nums = [float(n) for n in re.findall(r"-?[\d.]+", d)]
        out.append(list(zip(nums[::2], nums[1::2])))
    return out


def _drum_sheet(**kwargs) -> tuple[Flowsheet, units.Vessel, units.Instrument]:
    """Return a routed vertical drum with LG-101 on its east face."""
    fs = Flowsheet("level")
    drum = fs.add(units.Vessel("D-101")).pin(x=200, y=100)
    lg = fs.add_instrument("LG", 101, sensing=drum, face="E", **kwargs)
    fs.route()
    return fs, drum, lg


def _box(unit: units.Unit) -> tuple[float, float, float, float]:
    """Return a placed unit's frame as ``(x0, y0, x1, y1)``."""
    f = unit.frame
    assert f is not None
    return (f.x, f.y, f.x + f.w, f.y + f.h)


# --- two process taps ----------------------------------------------------------


def test_a_gauge_on_two_taps_draws_a_line_from_each_to_the_balloon():
    """Draw one impulse line from each tap on the drum's wall to the balloon between them."""
    fs, drum, lg = _drum_sheet(taps=(0.25, 0.55))
    x0, y0, x1, y1 = _box(drum)
    svg = fs.to_svg(check=False)
    lines = _polylines(_taps_group(svg))
    assert len(lines) == 2
    starts = sorted(line[0] for line in lines)
    upper, lower = y0 + 0.25 * (y1 - y0), y0 + 0.55 * (y1 - y0)
    assert [v for xy in starts for v in xy] == pytest.approx([x1, upper, x1, lower])
    bx0, by0, bx1, by1 = _box(lg)
    centre = ((bx0 + bx1) / 2, (by0 + by1) / 2)
    for line in lines:
        assert line[-1] == pytest.approx(centre)
    # The balloon hangs off the wall, level with the middle of its taps.
    assert centre[1] == pytest.approx((upper + lower) / 2) and centre[0] > x1
    assert "stroke-dasharray" not in _taps_group(svg)


def test_a_gauge_exports_both_tap_lines_to_drawio():
    """Write an edge for each tap line, from the drum's wall to the balloon."""
    fs, _drum, _lg = _drum_sheet(taps=(0.3, 0.7))
    root = ET.fromstring(fs.to_drawio(check=False))
    taps = [c for c in root.iter("mxCell") if re.fullmatch(r"t\d+", c.get("id") or "")]
    assert len(taps) == 2


@pytest.mark.parametrize(
    "kwargs,match",
    [
        ({"taps": (0.3,)}, "two fractions"),
        ({"taps": (0.3, 0.3)}, "two fractions"),
        ({"taps": (0.3, 1.2)}, "two fractions"),
        ({"taps": (0.3, 0.7), "face": None}, "face="),
        ({"taps": (0.01, 0.7)}, "off the E wall"),
    ],
)
def test_two_taps_are_refused_where_they_cannot_be_drawn(kwargs, match):
    """Refuse taps= that is not two fractions, has no face, or leaves the wall."""
    fs = Flowsheet("refused")
    drum = fs.add(units.Vessel("D-101"))
    face = kwargs.pop("face", "E")
    with pytest.raises(ValueError, match=match):
        fs.add_instrument("LG", 101, sensing=drum, face=face, **kwargs)
    assert [u.name for u in fs.units] == ["D-101"]


def test_two_taps_on_a_line_are_refused():
    """Refuse taps= on a balloon hung from a pipe, which has no wall."""
    fs = Flowsheet("pipe")
    a, b = fs.add(units.Feed("F")), fs.add(units.Product("P"))
    line = fs.connect(a.outlet, b.inlet)
    with pytest.raises(ValueError, match="face of a unit"):
        fs.add_instrument("LT", 101, sensing=line, taps=(0.3, 0.7))


# --- marks at the tap end ------------------------------------------------------


def _pipe_sheet(element: str) -> tuple[Flowsheet, float, float]:
    """Return a routed level pipe at y=200 with TT-101 above it, and the tap's x."""
    fs = Flowsheet("well")
    a = fs.add(units.Feed("F")).pin(x=100, y=200)
    b = fs.add(units.Product("P")).pin(x=500, y=200)
    line = fs.connect(a.outlet, b.inlet)
    tt = fs.add_instrument("TT", 101, sensing=line, at=0.5, element=element)
    fs.route()
    assert tt.tap is not None
    return fs, tt.tap[0], tt.tap[1]


def _marks(svg: str) -> str:
    """Return the tap-end marks drawn in the tap group."""
    return "".join(re.findall(r'<path d="[^"]+" fill="none" class="tap-end"[^>]*>', svg))


def _segments(marks: str) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Return the straight strokes of the marks' ``M``/``L`` paths."""
    out = []
    for d in re.findall(r'd="([^"]+)"', marks):
        if "A" in d:
            continue
        nums = [float(n) for n in re.findall(r"-?[\d.]+", d)]
        pts = list(zip(nums[::2], nums[1::2]))
        out += list(zip(pts, pts[1:]))
    return out


def test_a_thermowell_crosses_the_pipe_under_a_bar_outside_it():
    """Draw ISO 15519-2 A.4.10: a bar across the tap line and the well into the pipe."""
    fs, tx, ty = _pipe_sheet("thermowell")
    svg = fs.to_svg(check=False)
    strokes = _segments(_marks(svg))
    level = [s for s in strokes if abs(s[0][1] - s[1][1]) < 0.01]
    upright = [s for s in strokes if abs(s[0][0] - s[1][0]) < 0.01]
    # One bar, centred on the tap, on the balloon's side of the pipe.
    ((a, b),) = level
    assert (a[0] + b[0]) / 2 == pytest.approx(tx) and abs(b[0] - a[0]) >= 8
    assert 3 <= ty - a[1] <= 8
    # The well runs past the pipe's centre line, into the pipe.
    assert any(max(p[1], q[1]) >= ty + 3 and p[0] == pytest.approx(tx) for p, q in upright)


def _drum_with(element: str) -> tuple[Flowsheet, units.Vessel, units.Instrument]:
    """Return a routed drum with LT-101 on its top, carrying a level element."""
    fs = Flowsheet("level element")
    drum = fs.add(units.Vessel("D-101")).pin(x=200, y=100)
    lt = fs.add_instrument("LT", 101, sensing=drum, face="N", element=element)
    fs.route()
    return fs, drum, lt


def _inside(drum: units.Vessel, points) -> bool:
    """Return whether every point lies inside the drum's frame."""
    x0, y0, x1, y1 = _box(drum)
    return all(x0 < x < x1 and y0 < y < y1 for x, y in points)


def test_a_radar_sends_two_arcs_into_the_vessel():
    """Draw A.4.21: two arcs below the top tap, bowed into the vessel."""
    fs, drum, lt = _drum_with("radar")
    marks = _marks(fs.to_svg(check=False))
    arcs = re.findall(r"A [-\d.]+ [-\d.]+ 0 0 [01] ([-\d.]+) ([-\d.]+)", marks)
    starts = re.findall(r"M ([-\d.]+) ([-\d.]+) A", marks)
    assert len(arcs) == 2 and len(starts) == 2
    assert lt.tap is not None
    tx, ty = lt.tap
    ends = [(float(x), float(y)) for x, y in arcs + starts]
    assert _inside(drum, ends)
    # Each arc is level and centred on the tap, the second further in.
    (sa, ea), (sb, eb) = [
        ((float(s[0]), float(s[1])), (float(e[0]), float(e[1]))) for s, e in zip(starts, arcs)
    ]
    for s, e in ((sa, ea), (sb, eb)):
        assert s[1] == pytest.approx(e[1]) and (s[0] + e[0]) / 2 == pytest.approx(tx)
    assert ty < sa[1] < sb[1]


def test_a_vibrating_fork_hangs_two_prongs_in_the_vessel():
    """Draw A.4.22: an arch whose two legs point into the vessel."""
    fs, drum, lt = _drum_with("vibrating fork")
    marks = _marks(fs.to_svg(check=False))
    assert lt.tap is not None
    tx, ty = lt.tap
    legs = [s for s in _segments(marks) if abs(s[0][0] - s[1][0]) < 0.01 and abs(s[0][0] - tx) > 1]
    assert len(legs) == 2
    assert sorted(round(s[0][0] - tx, 3) for s in legs) == pytest.approx(
        [-(abs(legs[0][0][0] - tx)), abs(legs[0][0][0] - tx)]
    )
    assert "A " in marks
    assert _inside(drum, [p for s in legs for p in s])
    assert all(min(p[1] for p in s) > ty for s in legs)


def test_an_electrode_hangs_two_unequal_rods_from_a_bar():
    """Draw A.4.23: a level bar with a short rod and a long rod below it."""
    fs, drum, lt = _drum_with("electrode")
    marks = _marks(fs.to_svg(check=False))
    assert lt.tap is not None
    tx, _ty = lt.tap
    strokes = _segments(marks)
    bars = [s for s in strokes if abs(s[0][1] - s[1][1]) < 0.01]
    rods = [s for s in strokes if abs(s[0][0] - s[1][0]) < 0.01 and abs(s[0][0] - tx) > 1]
    assert len(bars) == 1 and len(rods) == 2
    lengths = sorted(abs(s[1][1] - s[0][1]) for s in rods)
    assert lengths[1] > lengths[0] + 2
    assert _inside(drum, [p for s in rods + bars for p in s])
    assert "A " not in marks


def test_a_tap_end_mark_exports_to_drawio_at_the_tap():
    """Write a mark as a stencil cell over the tap, where the sheet draws it."""
    fs, tx, ty = _pipe_sheet("thermowell")
    root = ET.fromstring(fs.to_drawio(check=False))
    cells = {c.get("id", ""): c for c in root.iter("mxCell")}
    marks = [c for cid, c in cells.items() if cid.endswith("-mark")]
    assert len(marks) == 1
    assert "shape=stencil(" in (marks[0].get("style") or "")
    # The page placement, read off the balloon's own cell.
    tt = next(u for u in fs.units if u.name == "TT-101")
    balloon = next(c for c in cells.values() if (c.get("value") or "").startswith("TT"))
    own, box = balloon.find("mxGeometry"), marks[0].find("mxGeometry")
    assert own is not None and box is not None and tt.frame is not None
    scale = float(own.get("width", 0)) / tt.frame.w
    px = float(own.get("x", 0)) + (tx - tt.frame.x) * scale
    py = float(own.get("y", 0)) + (ty - tt.frame.y) * scale
    x, y = float(box.get("x", 0)), float(box.get("y", 0))
    w, h = float(box.get("width", 0)), float(box.get("height", 0))
    # A bar one module wide, half a module out, over a well half a module in.
    assert (w / scale, h / scale) == pytest.approx((10.0, 10.0), abs=0.1)
    assert (x + w / 2, y + h / 2) == pytest.approx((px, py), abs=0.1)


@pytest.mark.parametrize("element", ["", "float", "Thermowell "])
def test_an_unknown_element_is_refused_naming_the_ones_drawn(element):
    """Refuse an element the sheet has no mark for, listing those it has."""
    if element.strip().lower() == "thermowell":
        assert units.Instrument("TT", 1, element=element).element == "thermowell"
        return
    with pytest.raises(ValueError, match="'vibrating fork'"):
        units.Instrument("LT", 1, element=element)


def test_taps_and_element_read_back_from_a_spec():
    """Keep taps= and element= through ``to_dict`` and ``from_dict``."""
    fs = Flowsheet("spec")
    drum = fs.add(units.Vessel("D-101"))
    fs.add_instrument("LG", 101, sensing=drum, face="E", taps=(0.3, 0.7))
    fs.add_instrument("LT", 102, sensing=drum, face="N", element="radar")
    read = {u.name: u for u in Flowsheet.from_dict(fs.to_dict()).units}
    lg, lt = read["LG-101"], read["LT-102"]
    assert isinstance(lg, units.Instrument) and isinstance(lt, units.Instrument)
    assert lg.taps == (0.3, 0.7) and lt.element == "radar"


def test_a_plain_balloon_draws_one_tap_and_no_mark():
    """Leave a balloon without taps= or element= drawn as before."""
    fs, _drum, _lg = _drum_sheet()
    svg = fs.to_svg(check=False)
    assert len(_polylines(_taps_group(svg))) == 1
    assert _marks(svg) == ""
    assert math.isfinite(1.0)


@pytest.mark.parametrize(
    "kwargs",
    [{"element": "radar"}, {"taps": (0.3, 0.7)}, {"element": "thermowell", "near": True}],
)
def test_a_tap_end_with_no_tap_line_is_reported(kwargs):
    """Warn where element= or taps= has no tap line to be drawn on."""
    fs = Flowsheet("undrawn")
    drum = fs.add(units.Vessel("D-101"))
    if kwargs.pop("near", False):
        fs.add_instrument("TT", 101, near=drum, **kwargs)
    else:
        fs.add(units.Instrument("LT", 101, **kwargs))
    found = [w for w in fs.validate() if w.code == "tap-end-undrawn"]
    assert len(found) == 1 and "sensing=" in found[0].message


# --- taps on the shell, not on the parts it carries ----------------------------

#: The default vertical vessel's shell: 62 wide, 100 tall.
_SHELL_W, _SHELL_H = 62.0, 100.0


def test_a_single_tap_on_a_face_with_a_manhole_starts_on_the_shell():
    """Start a balloon's tap line on the shell, not at the manhole's reach."""
    fs = Flowsheet("manhole")
    drum = fs.add(units.Vessel("D-101", manholes=[("W", 0.5)])).pin(x=200, y=100)
    fs.add_instrument("LT", 101, sensing=drum, face="W")
    fs.route()
    x0, y0, x1, _y1 = _box(drum)
    assert x1 - x0 > _SHELL_W, "the premise: the manhole widens the drum's box"
    (line,) = _polylines(_taps_group(fs.to_svg(check=False)))
    assert line[0][0] == pytest.approx(x1 - _SHELL_W)


@pytest.mark.parametrize(
    "parts",
    [
        {"manholes": [("E", 0.5)]},
        {"sockets": [("E", 0.5)]},
        {"supports": "leg"},
        {"supports": "skirt"},
    ],
    ids=["manhole", "socket", "legs", "skirt"],
)
def test_two_taps_sit_on_the_shell_wall_whatever_it_carries(parts):
    """Put both taps on the shell, at fractions of the shell, not of the grown box."""
    fs = Flowsheet("level")
    drum = fs.add(units.Vessel("D", **parts)).pin(x=200, y=100)
    fs.add_instrument("LG", 1, sensing=drum, face="E", taps=(0.3, 0.7))
    fs.route()
    x0, y0, x1, y1 = _box(drum)
    assert (x1 - x0, y1 - y0) != (_SHELL_W, _SHELL_H), "the premise: a part grows the box"
    starts = sorted(line[0] for line in _polylines(_taps_group(fs.to_svg(check=False))))
    # The shell is the box's top-left 62 x 100 here: parts grow it east or down.
    flat = [v for xy in starts for v in xy]
    assert flat == pytest.approx([x0 + _SHELL_W, y0 + 30.0, x0 + _SHELL_W, y0 + 70.0])
    root = ET.fromstring(fs.to_drawio(check=False))
    edges = [c for c in root.iter("mxCell") if re.fullmatch(r"t\d+", c.get("id") or "")]
    # draw.io leaves the drum's cell, the whole box, at the same two points.
    exits = sorted(
        (float(m["exitX"]), float(m["exitY"]))
        for e in edges
        for m in [dict(kv.split("=", 1) for kv in (e.get("style") or "").split(";") if "=" in kv)]
    )
    w, h = x1 - x0, y1 - y0
    want = [_SHELL_W / w, 30.0 / h, _SHELL_W / w, 70.0 / h]
    assert [v for xy in exits for v in xy] == pytest.approx(want, abs=1e-3)


def test_a_tap_on_a_stirred_vessels_top_stays_on_its_motor():
    """Keep the motor a speed transmitter senses: only wall parts are left out."""
    fs = Flowsheet("stirred")
    rx = fs.add(units.Vessel("R-101", agitator="turbine", supports="leg")).pin(x=200, y=100)
    fs.add_instrument("ST", 101, sensing=rx, face="N")
    fs.route()
    _x0, y0, _x1, _y1 = _box(rx)
    (line,) = _polylines(_taps_group(fs.to_svg(check=False)))
    assert line[0][1] == pytest.approx(y0)


@pytest.mark.parametrize("key,value", [("element", "radar"), ("taps", [0.3, 0.7])])
def test_a_primary_elements_balloon_in_a_spec_refuses_taps_and_element(key, value):
    """Refuse taps: and element: on a balloon_of entry, which reads neither."""
    from pandid.spec import SpecError

    spec = {
        "name": "x",
        "units": [{"kind": "FlowElement", "name": "FE-1"}],
        "instruments": [{"balloon_of": "FE-1", key: value}],
    }
    with pytest.raises(SpecError, match=f"unknown key '{key}'"):
        Flowsheet.from_dict(spec)
