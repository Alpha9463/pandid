"""Check what label halos, flange marks and letter codes may cover on every corpus sheet."""

import html
import math
import re
from typing import NamedTuple

import pytest

from _layout_cases import overlaps
from pandid import Flowsheet, units as U
from pandid.portgeom import unit_box
from pandid.render.svg import _PLATE_CLEARANCE, _ink, _obstacle
from pandid.render.weights import LineWeight

from test_label_invariants import CORPUS

_HALO = re.compile(
    r'<rect x="([-\d.]+)" y="([-\d.]+)" width="([\d.]+)" '
    r'height="([\d.]+)" fill="white" />'
)


def _halos(svg: str) -> "list[tuple[float, float, float, float]]":
    """Return every opaque plate a label pass drew, from the drawn sheet."""
    body = svg.split("</defs>", 1)[1]
    return [
        (
            float(m.group(1)),
            float(m.group(2)),
            float(m.group(1)) + float(m.group(3)),
            float(m.group(2)) + float(m.group(4)),
        )
        for m in _HALO.finditer(body)
    ]


class Face(NamedTuple):
    """One drawn flange face, and the joint it belongs to."""

    box: tuple  # the rectangle this bar's stroke covers
    at: tuple  # the *pair's* centre, which is the joint the pair straddles
    port: object  # the nozzle it stands off


def _flange_bars(fs, kwargs) -> "list[Face]":
    """Return every flange face on a sheet."""
    from pandid.render.svg import (
        FLANGE_GAP,
        FLANGE_TICK,
        flange_marks,
        resolve_connections,
        sheet_connections,
        stream_polyline,
    )

    joints = sheet_connections(kwargs.get("diagram"), kwargs.get("connections"))
    out = []
    for s in fs.streams:
        pts = stream_polyline(s)
        for m in flange_marks(s, pts, resolve_connections(s, joints)):
            at_source = math.dist((m.x, m.y), pts[0]) <= math.dist((m.x, m.y), pts[-1])
            port = s.source if at_source else s.dest
            rad = math.radians(m.angle)
            ax, ay = math.cos(rad) * FLANGE_GAP / 2, math.sin(rad) * FLANGE_GAP / 2
            bx, by = -math.sin(rad) * FLANGE_TICK / 2, math.cos(rad) * FLANGE_TICK / 2
            for sign in (-1.0, 1.0):
                cx, cy = m.x + ax * sign, m.y + ay * sign
                out.append(
                    Face(
                        (
                            min(cx - bx, cx + bx),
                            min(cy - by, cy + by),
                            max(cx - bx, cx + bx),
                            max(cy - by, cy + by),
                        ),
                        (m.x, m.y),
                        port,
                    )
                )
    return out


class Drawn(NamedTuple):
    """One rendered corpus sheet, and the ink these checks weigh against it."""

    fs: object
    halos: list
    bars: list
    codes: list


@pytest.fixture(scope="module")
def drawn(corpus_svg):
    """Find the halos and flange faces of every corpus sheet once."""
    return {
        name: Drawn(fs, _halos(svg), _flange_bars(fs, options), _code_boxes(svg, fs))
        for name, (fs, options, svg) in corpus_svg.items()
    }


def _inked(box):
    """Return a symbol's box grown by the half-pen that is drawn outside it."""
    half = LineWeight.EQUIPMENT.width / 2
    return (box[0] - half, box[1] - half, box[2] + half, box[3] + half)


@pytest.mark.parametrize("name", list(CORPUS), ids=list(CORPUS))
def test_no_halo_lands_on_a_graphical_symbol(drawn, name):
    """Check that no halo lands on a graphical symbol."""
    fs, halos, _bars, _codes = drawn[name]
    symbols = [(u, unit_box(u, u.frame)) for u in fs.units if u.frame is not None]
    # A tag inside its own symbol has no halo, so every plate belongs outside one.
    broken = [
        f"{u.tag or u.kind} at ({box[0]:.0f}, {box[1]:.0f})"
        for halo in halos
        for u, box in symbols
        if overlaps(halo, _inked(box))
    ]
    assert not broken, f"{name}: halo over the ink of " + "; ".join(sorted(set(broken)))


@pytest.mark.parametrize("name", list(CORPUS), ids=list(CORPUS))
def test_no_halo_is_written_hard_against_an_outline(drawn, name):
    """Check that no halo is written hard against an outline."""
    fs, halos, _bars, _codes = drawn[name]
    symbols = [(u, unit_box(u, u.frame)) for u in fs.units if u.frame is not None]
    crowded = [
        f"{u.tag or u.kind} at ({box[0]:.0f}, {box[1]:.0f})"
        for halo in halos
        for u, box in symbols
        if overlaps(halo, _obstacle(box))
    ]
    assert not crowded, f"{name}: halo within {_PLATE_CLEARANCE}u of " + "; ".join(
        sorted(set(crowded))
    )


@pytest.mark.parametrize("name", list(CORPUS), ids=list(CORPUS))
def test_no_halo_lands_on_an_impulse_line(drawn, name):
    """Check that no halo lands on an impulse line."""
    fs, halos, _bars, _codes = drawn[name]
    taps = [line.box for line in _ink(fs, "vertical") if line.kind == "tap"]
    cut = [
        f"({box[0]:.0f}, {box[1]:.0f})-({box[2]:.0f}, {box[3]:.0f})"
        for halo in halos
        for box in taps
        if overlaps(halo, box)
    ]
    assert not cut, f"{name}: halo over the impulse line at " + "; ".join(sorted(set(cut)))


def test_the_corpus_has_impulse_lines_to_check(drawn):
    """Check that the corpus has impulse lines to check."""
    counted = {
        name: sum(1 for line in _ink(fs, "vertical") if line.kind == "tap")
        for name, (fs, _halos, _bars, _codes) in drawn.items()
    }
    assert counted["10_ethanol_pid"] > 15, counted
    assert counted["13_tank_farm"] > 10, counted


def test_the_corpus_has_halos_to_check(drawn):
    """Check that the corpus has halos to check."""
    counted = {name: len(halos) for name, (_fs, halos, _bars, _codes) in drawn.items()}
    assert all(counted.values()), counted
    assert counted["10_ethanol_pid"] > 50, counted


# --- and the same question from the other side: the flange marks --------------


@pytest.mark.parametrize("name", list(CORPUS), ids=list(CORPUS))
def test_no_flange_mark_lands_on_a_symbol_it_is_not_the_joint_for(drawn, name):
    """Check that no flange mark lands on a symbol it is not the joint for."""
    fs, _halos_, bars, _codes = drawn[name]
    symbols = [(u, unit_box(u, u.frame)) for u in fs.units if u.frame is not None]
    over = [
        f"{u.tag or u.kind} at ({box[0]:.0f}, {box[1]:.0f})"
        for face in bars
        for u, box in symbols
        if u is not face.port.owner and overlaps(face.box, _inked(box))
    ]
    assert not over, f"{name}: flange face over the ink of " + "; ".join(sorted(set(over)))


@pytest.mark.parametrize("name", list(CORPUS), ids=list(CORPUS))
def test_a_flange_mark_is_drawn_on_the_outside_of_its_own_nozzle(drawn, name):
    """Check that a flange mark is drawn on the outside of its own nozzle."""
    from pandid.portgeom import port_point

    fs, _halos_, bars, _codes = drawn[name]
    inward = []
    for face in bars:
        u = face.port.owner
        if u.frame is None:
            continue
        x0, y0, x1, y1 = unit_box(u, u.frame)
        mid = ((x0 + x1) / 2, (y0 + y1) / 2)
        nozzle = port_point(u, u.frame, face.port.name)
        if math.dist(face.at, mid) <= math.dist(nozzle, mid):
            inward.append(f"{u.tag or u.kind}.{face.port.name}")
    assert not inward, f"{name}: flange stepped inward at " + "; ".join(sorted(set(inward)))


@pytest.mark.parametrize("name", list(CORPUS), ids=list(CORPUS))
def test_no_flange_mark_lands_on_a_tag_or_a_line_number(drawn, name):
    """Check that no flange mark lands on a tag or a line number."""
    fs, halos, bars, _codes = drawn[name]
    hit = [
        f"({face.box[0]:.0f}, {face.box[1]:.0f})"
        for face in bars
        for halo in halos
        if overlaps(face.box, halo)
    ]
    assert not hit, f"{name}: a halo deletes the flange face at " + "; ".join(sorted(set(hit)))


def test_the_corpus_has_flange_marks_to_check(drawn):
    """Check that the corpus has flange marks to check."""
    counted = {name: len(bars) for name, (_fs, _halos_, bars, _codes) in drawn.items()}
    # Two faces per mark on every nozzle and in-line body of the densest sheet.
    assert counted["10_ethanol_pid"] > 80, counted
    assert all(n % 2 == 0 for n in counted.values()), (
        "a flange is a pair of faces and they are drawn together"
    )


# --- letter codes written outside a symbol ------------------------------------
# A letter code clears every line, pipe and signal alike, and the label passes dodge it.


_LABEL = re.compile(
    r'<rect x="([-\d.]+)" y="([-\d.]+)" width="([\d.]+)" height="([\d.]+)" fill="white" />'
    r"\s*<text [^>]*>([^<]*)</text>"
)


def _code_boxes(svg: str, fs) -> "list[tuple[float, float, float, float]]":
    """Return the halo of every letter code the sheet writes outside a symbol."""
    written = {
        code for u in fs.units for codes in getattr(u, "quadrants", {}).values() for code in codes
    }
    group = svg.split('<g id="unit_labels">', 1)[-1].split("</g>", 1)[0]
    return [
        (float(x), float(y), float(x) + float(w), float(y) + float(h))
        for x, y, w, h, text in _LABEL.findall(group)
        if html.unescape(text) in written
    ]


@pytest.mark.parametrize("name", list(CORPUS), ids=list(CORPUS))
def test_no_letter_code_lands_on_a_line(drawn, name):
    """Check that no letter code lands on a line."""
    fs, _halos_, _bars, codes = drawn[name]
    struck = [
        f"({box[0]:.0f}, {box[1]:.0f}) on {line.kind}"
        for box in codes
        for line in _ink(fs, "vertical")
        if overlaps(box, line.box)
    ]
    assert not struck, f"{name}: a letter code lies on " + "; ".join(sorted(set(struck)))


@pytest.mark.parametrize("name", list(CORPUS), ids=list(CORPUS))
def test_no_letter_code_lands_on_a_tag_or_a_line_number(drawn, name):
    """Check that no letter code lands on a tag or a line number."""
    _fs, halos, _bars, codes = drawn[name]
    others = [
        h
        for h in halos
        if not any(all(abs(a - b) < 0.2 for a, b in zip(h, code)) for code in codes)
    ]
    hit = [
        f"({box[0]:.0f}, {box[1]:.0f})" for box in codes for other in others if overlaps(box, other)
    ]
    assert not hit, f"{name}: a letter code is written over a label at " + "; ".join(
        sorted(set(hit))
    )


def _codes_between_a_flange_and_a_line() -> "tuple[Flowsheet, dict]":
    """Build a flanged sheet whose alarm codes have no spot clear of both a flange and a line."""
    fs = Flowsheet("codes between a flange and a line")
    feed = fs.add(U.Feed("F"))
    valve = fs.add(U.Valve("HV-1"))
    prod = fs.add(U.Product("P"))
    feed.pin(port="outlet", x=300, y=300)
    valve.pin(port="inlet", x=380, y=240)
    prod.pin(port="inlet", x=580, y=240)
    riser = fs.connect(feed.outlet, valve.inlet)
    fs.connect(valve.outlet, prod.inlet)
    pi = fs.add_instrument("PI", 1, sensing=riser, at=0.6)
    pi.annotate(high="PAH", low="PAL").pin(x=301.18, y=217.18)
    other, out = fs.add(U.Feed("F2")), fs.add(U.Product("P2"))
    other.pin(port="outlet", x=100, y=229)
    out.pin(port="inlet", x=600, y=100)
    fs.connect(other.outlet, out.inlet).via([(290, 229), (290, 100)])
    return fs, {"diagram": "p&id", "connections": "flanged"}


def _codes_beside_a_fixed_tag() -> "tuple[Flowsheet, dict]":
    """Build a flanged sheet whose codes could leave a flange only for a tag set in place."""
    fs, kwargs = CORPUS["codes_beside_a_flange"]()
    fs.add(U.Valve("HV-2", label_pos="bottom")).pin(x=70, y=98)
    return fs, kwargs


def _codes_beside_another_balloon() -> "tuple[Flowsheet, dict]":
    """Build a flanged sheet whose moved codes could crowd a later balloon's onto a line."""
    fs, kwargs = CORPUS["codes_beside_a_flange"]()
    feed, valve, prod, pi = fs.units[:4]
    feed.pin(port="outlet", x=400, y=500)
    valve.pin(port="inlet", x=480, y=440)
    prod.pin(port="inlet", x=680, y=440)
    pi.pin(x=401.18, y=417.18)
    fs.add_instrument("TI", 2).annotate(high="TAH", low="TAL").pin(x=300, y=417)
    other, out = fs.add(U.Feed("F2")), fs.add(U.Product("P2"))
    other.pin(port="outlet", x=100, y=429)
    out.pin(port="inlet", x=600, y=330)
    fs.connect(other.outlet, out.inlet).via([(290, 429), (290, 330)])
    return fs, kwargs


def _codes_between_a_line_and_a_balloon() -> "tuple[Flowsheet, dict]":
    """Build a sheet whose pair of codes has a line on one side and another balloon's on the other."""
    fs, kwargs = _codes_beside_another_balloon()
    fs.units[3].pin(x=389.53, y=437.35)
    return fs, kwargs


def _codes_beside_a_closed_valve() -> "tuple[Flowsheet, dict]":
    """Build a flanged sheet whose codes could leave a flange only for a valve's NC."""
    fs, kwargs = CORPUS["codes_beside_a_flange"]()
    fs.add(U.Valve("HV-3", variant="butterfly", normal_position="closed")).pin(x=20, y=144)
    return fs, kwargs


def _codes_beside_a_pneumatic_line() -> "tuple[Flowsheet, dict]":
    """Build a flanged sheet whose codes could leave a flange only for a pneumatic hatch."""
    fs = Flowsheet("pneumatic hatch")
    feed = fs.add(U.Feed("F")).pin(port="outlet", x=400, y=200)
    valve = fs.add(U.Valve("HV-1")).pin(port="inlet", x=480, y=140)
    prod = fs.add(U.Product("P")).pin(port="inlet", x=680, y=140)
    riser = fs.connect(feed.outlet, valve.inlet)
    fs.connect(valve.outlet, prod.inlet)
    pi = fs.add_instrument("PI", 1, sensing=riser, at=0.6)
    pi.annotate(high="PAH", low="PAL").pin(x=401.18, y=117.18)
    relay = fs.add_instrument("PY", 2).pin(port="sig_out", x=350, y=119.5)
    controller = fs.add_instrument("PIC", 3).pin(port="sig_in", x=600, y=40)
    signal = fs.connect(relay.sig_out, controller.sig_in, kind="pneumatic")
    signal.via([(400, 119.5), (400, 40)])
    return fs, {"diagram": "p&id", "connections": "flanged"}


def _codes_beside_a_stacked_tag() -> "tuple[Flowsheet, dict]":
    """Build a flanged sheet whose codes could leave a flange only for a tag stacked with NC."""
    fs, kwargs = CORPUS["codes_beside_a_flange"]()
    feed, valve, prod, pi = fs.units[:4]
    feed.pin(port="outlet", x=300, y=200)
    valve.pin(port="inlet", x=380, y=140)
    prod.pin(port="inlet", x=580, y=140)
    pi.pin(x=301.18, y=117.18)
    closed = fs.add(
        U.Valve("HV-2", variant="butterfly", normal_position="closed", label_pos="bottom")
    ).pin(x=260, y=80)
    other = fs.add(U.Feed("F2")).pin(port="outlet", x=100, y=90)
    out = fs.add(U.Product("P2")).pin(port="inlet", x=500, y=90)
    fs.connect(other.outlet, closed.inlet)
    fs.connect(closed.outlet, out.inlet)
    return fs, kwargs


def _hatch_bars(fs) -> "list[tuple[float, float, float, float]]":
    """Return the box of every pneumatic hatch stroke on a sheet."""
    from pandid.render.svg import HATCH_ALONG, HATCH_ARM, pneumatic_marks, stream_polyline

    along, across = HATCH_ARM
    out = []
    for s in fs.streams:
        if s.kind != "pneumatic":
            continue
        for mark in pneumatic_marks(stream_polyline(s)):
            for off in HATCH_ALONG:
                dx, dy = (off - along, off + along), (-across, across)
                xs, ys = (dx, dy) if mark.horizontal else (dy, dx)
                out.append((mark.x + xs[0], mark.y + ys[0], mark.x + xs[1], mark.y + ys[1]))
    return out


#: Flanged sheets where a letter code by a flange mark has nowhere better to go.
CROWDED_CODES = {
    "a_flange_and_a_line": _codes_between_a_flange_and_a_line,
    "a_fixed_tag": _codes_beside_a_fixed_tag,
    "another_balloon": _codes_beside_another_balloon,
    "a_line_and_a_balloon": _codes_between_a_line_and_a_balloon,
    "a_closed_valve": _codes_beside_a_closed_valve,
    "a_pneumatic_line": _codes_beside_a_pneumatic_line,
    "a_stacked_tag": _codes_beside_a_stacked_tag,
}


@pytest.mark.parametrize("build", list(CROWDED_CODES.values()), ids=list(CROWDED_CODES))
def test_a_letter_code_by_a_flange_mark_lands_on_no_line_or_label(build):
    """Check that a letter code by a flange mark lands on no line, hatch or other label."""
    fs, kwargs = build()
    svg = fs.to_svg(**kwargs)
    codes = _code_boxes(svg, fs)
    labels = [
        h
        for h in _halos(svg)
        if not any(all(abs(a - b) < 0.2 for a, b in zip(h, code)) for code in codes)
    ]
    struck = (
        [
            f"({box[0]:.0f}, {box[1]:.0f}) on {line.kind}"
            for box in codes
            for line in _ink(fs, "vertical")
            if overlaps(box, line.box)
        ]
        + [
            f"({box[0]:.0f}, {box[1]:.0f}) on a label"
            for box in codes
            for h in labels
            if overlaps(box, h)
        ]
        + [
            f"({box[0]:.0f}, {box[1]:.0f}) on a hatch"
            for box in codes
            for bar in _hatch_bars(fs)
            if overlaps(box, bar)
        ]
    )
    assert not struck, "a letter code lies " + "; ".join(sorted(set(struck)))


def test_the_corpus_has_letter_codes_to_check(drawn):
    """Check that the corpus has letter codes to check."""
    counted = {name: len(codes) for name, (_fs, _h, _b, codes) in drawn.items()}
    assert counted["03_control_loop"] == 2, counted
    assert counted["10_ethanol_pid"] == 6, counted
    assert counted["13_tank_farm"] == 5, counted


def _tag_halo(svg: str, tag: str) -> "tuple[float, float, float, float]":
    """Return the halo drawn behind one tag."""
    m = re.search(_HALO.pattern + rf"\s*<text[^>]*>{re.escape(tag)}<", svg)
    assert m is not None, f"no halo behind {tag}"
    x, y, w, h = (float(v) for v in m.groups())
    return (x, y, x + w, y + h)


def test_a_tag_boxed_in_by_balloons_takes_a_nozzle_side_clear_of_them():
    """Check that a tag whose free sides are under balloons is drawn clear of them."""
    fs = Flowsheet("boxed in")
    feed = fs.add(U.Feed("F"))
    pump = fs.add(U.Pump("P-1")).pin(x=300, y=200)
    prod = fs.add(U.Product("P"))
    suction = fs.connect(feed.outlet, pump.suction)
    discharge = fs.connect(pump.discharge, prod.inlet)
    above = fs.add_instrument("PI", 1, sensing=suction).pin(x=313, y=150)
    below = fs.add_instrument("PI", 2, sensing=discharge).pin(x=313, y=272)
    halo = _tag_halo(fs.to_svg(), "P-1")
    for balloon in (above, below):
        assert balloon.frame is not None
        assert not overlaps(halo, _inked(unit_box(balloon, balloon.frame))), balloon.tag


def test_a_tag_keeps_off_the_tag_of_the_valve_beside_it():
    """Check that two valves close on one line write their tags apart."""
    fs = Flowsheet("close valves")
    feed = fs.add(U.Feed("F")).pin(port="outlet", x=100, y=200)
    first = fs.add(U.Valve("HV-101")).pin(port="inlet", x=200, y=200)
    second = fs.add(U.Valve("HV-102")).pin(port="inlet", x=240, y=200)
    prod = fs.add(U.Product("P")).pin(port="inlet", x=400, y=200)
    fs.connect(feed.outlet, first.inlet)
    fs.connect(first.outlet, second.inlet)
    fs.connect(second.outlet, prod.inlet)
    svg = fs.to_svg()
    assert not overlaps(_tag_halo(svg, "HV-101"), _tag_halo(svg, "HV-102"))


@pytest.mark.parametrize("name", list(CORPUS), ids=list(CORPUS))
def test_no_halo_lands_on_another_halo(drawn, name):
    """Check that no two label halos overlap."""
    halos = drawn[name].halos
    struck = [
        f"({a[0]:.0f}, {a[1]:.0f}) and ({b[0]:.0f}, {b[1]:.0f})"
        for i, a in enumerate(halos)
        for b in halos[i + 1 :]
        if overlaps(a, b)
    ]
    assert not struck, f"{name}: halos overlap at " + "; ".join(struck)


def test_a_tag_moved_off_a_label_erases_no_line():
    """Check that tags kept off each other on a crowded bank erase no line."""
    from test_instrument_banks import _valved_bank

    fs, _loops = _valved_bank(100, controller_face="E")
    assert not _erased_lines(fs, fs.to_svg(diagram="p&id"))


def _two_pump_bank(face: str) -> Flowsheet:
    """Build two pumps in parallel, a flow loop on each one's valved suction."""
    from test_instruments import _valved_bank

    return _valved_bank(100, controller_face=face, route=False, pumps=2)[0]


def _erased_lines(fs: Flowsheet, svg: str) -> list[str]:
    """Return each line a tag's halo erases on the drawn sheet."""
    tags = [u.tag for u in fs.units if u.kind not in ("feed", "product", "instrument")]
    return [
        f"{tag} on {line.kind} at ({line.box[0]:.0f}, {line.box[1]:.0f})"
        for tag in tags
        for line in _ink(fs, "vertical")
        if overlaps(_tag_halo(svg, tag), line.box)
    ]


def test_a_valve_tag_on_a_small_bank_steps_off_the_lines_round_it():
    """Check that a valve's tag with no clear spot beside its face is written off every line."""
    fs = _two_pump_bank("S")
    assert not _erased_lines(fs, fs.to_svg(diagram="p&id"))


def test_a_tag_takes_the_next_spot_when_the_best_erases_more_line(monkeypatch):
    """Check that the tag pass passes over a spot that erases more line than the first."""
    from pandid.render.svg import SvgRenderer, unit_tags

    fs = Flowsheet("one valve")
    feed = fs.add(U.Feed("F")).pin(port="outlet", x=100, y=200)
    valve = fs.add(U.Valve("HV-1")).pin(port="inlet", x=200, y=200)
    prod = fs.add(U.Product("P")).pin(port="inlet", x=400, y=200)
    fs.connect(feed.outlet, valve.inlet)
    fs.connect(valve.outlet, prod.inlet)
    fs.route()
    place = SvgRenderer._tag_spots
    aside: list = []

    def across_the_line(
        self, u, f, x, y, w, h, tag, ink, symbols=(), labels=None, hatches=(), step_out=True
    ):
        """Rank a spot across the outlet line first, then one beside the first."""
        spots = place(self, u, f, x, y, w, h, tag, ink, symbols, labels, hatches, step_out)
        if labels is None:
            return spots
        aside.append((spots[-1][0] - 6, *spots[-1][1:]))
        return [(x + w + 10, y + h / 2, "start", "middle", "right", tag), aside[0], *spots]

    monkeypatch.setattr(SvgRenderer, "_tag_spots", across_the_line)
    ((_unit, tag, _items),) = unit_tags(fs, None, "vertical")
    assert aside and tag == aside[0], tag


def test_a_tag_may_pass_over_a_label_still_to_move_on_its_way_clear():
    """Check that tags on two rows of close valves end clear of each other."""
    fs = Flowsheet("valve rows")
    rows = {
        200: [("HV-100", 200, "closed", ""), ("FV-101", 250, "open", "closed")]
        + [("FV-102", 290, "open", "closed"), ("FV-103", 340, "open", "closed")],
        275: [("FV-111", 245, "open", "open"), ("HV-112", 290, "open", "")],
    }
    for y, valves in rows.items():
        before = fs.add(U.Feed(f"F{y}")).pin(port="outlet", x=100, y=y).outlet
        for tag, x, normal, fail in valves:
            valve = U.Valve(
                tag, "control" if fail else "default", normal_position=normal, fail=fail
            )
            fs.add(valve).pin(port="inlet", x=x, y=y)
            fs.connect(before, valve.inlet)
            before = valve.outlet
        fs.connect(before, fs.add(U.Product(f"P{y}")).pin(port="inlet", x=700, y=y).inlet)
    svg = fs.to_svg(diagram="p&id")
    tags = {u.tag: _tag_halo(svg, u.tag) for u in fs.units if u.kind == "valve"}
    names = sorted(tags)
    struck = [
        (a, b) for i, a in enumerate(names) for b in names[i + 1 :] if overlaps(tags[a], tags[b])
    ]
    assert not struck, struck


def test_a_tag_stepped_out_stays_nearer_its_own_unit():
    """Check that a tag with no clear spot near its valve is not left by another unit."""
    fs = _two_pump_bank("N")
    svg = fs.to_svg(diagram="p&id")
    tagged = [
        u
        for u in fs.units
        if u.kind not in ("feed", "product", "instrument") and u.frame is not None
    ]
    astray = []
    for u in tagged:
        halo = _tag_halo(svg, u.tag)
        gap = {v.tag: _gap(halo, unit_box(v, v.frame)) for v in tagged if v.frame is not None}
        astray += [f"{u.tag} by {v}" for v, g in gap.items() if v != u.tag and g < gap[u.tag]]
    assert not astray, astray


def _gap(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    """Return the distance between two boxes, 0 where they meet."""
    return math.hypot(max(b[0] - a[2], a[0] - b[2], 0.0), max(b[1] - a[3], a[1] - b[3], 0.0))


def test_a_tag_keeps_off_the_hatch_marks_of_a_pneumatic_signal():
    """Check that no tag's halo erases a hatch mark on a control valve's signal."""
    fs = _two_pump_bank("W")
    svg = fs.to_svg(diagram="p&id")
    tags = [u.tag for u in fs.units if u.kind not in ("feed", "product", "instrument")]
    struck = [tag for tag in tags for bar in _hatch_bars(fs) if overlaps(_tag_halo(svg, tag), bar)]
    assert not struck, struck


def test_a_tag_moved_off_a_tag_clips_no_symbol():
    """Check that tags on two close trains of valves keep off every symbol."""
    fs = Flowsheet("two trains")
    for row, y in ((0, 200), (1, 235)):
        before = fs.add(U.Feed(f"F{row}")).pin(port="outlet", x=100, y=y).outlet
        for i, x in enumerate((200, 240, 280)):
            valve = fs.add(U.Valve(f"HV-1{row}{i}")).pin(port="inlet", x=x, y=y)
            fs.connect(before, valve.inlet)
            before = valve.outlet
        fs.connect(before, fs.add(U.Product(f"P{row}")).pin(port="inlet", x=500, y=y).inlet)
    svg = fs.to_svg()
    valves = [u for u in fs.units if u.kind == "valve"]
    clipped = [
        f"{tag.tag} over {u.tag}"
        for tag in valves
        for u in valves
        if u is not tag
        and u.frame is not None
        and overlaps(_tag_halo(svg, tag.tag), _inked(unit_box(u, u.frame)))
    ]
    assert not clipped, "; ".join(clipped)
