"""Check what label halos, flange marks and letter codes may cover on every corpus sheet."""

import html
import math
import re
from typing import NamedTuple

import pytest

from _layout_cases import overlaps
from _render_cases import copy_settled_case
from pandid import Flowsheet, units as U
from pandid.portgeom import unit_box
from pandid.render.svg import _PLATE_CLEARANCE, _ink, _obstacle
from pandid.render.weights import LineWeight

from test_label_invariants import CORPUS, _RENDER_OPTS

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
def drawn(settled_gallery):
    """Render every halo-invariant corpus sheet once.

    Parameters
    ----------
    settled_gallery : dict[str, tuple[Flowsheet, dict]]
        Shared, routed gallery flowsheets and their render options.

    Returns
    -------
    dict
        Rendered flowsheets, label halos, flange faces and letter-code halos
        keyed by corpus name.
    """
    out = {}
    for name, build in CORPUS.items():
        if name in settled_gallery:
            fs, kwargs = copy_settled_case(settled_gallery, name)
        else:
            fs, kwargs = build()
        svg = fs.to_svg(**{k: v for k, v in kwargs.items() if k in _RENDER_OPTS})
        out[name] = Drawn(fs, _halos(svg), _flange_bars(fs, kwargs), _code_boxes(svg, fs))
    return out


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
    assert counted["11_ethanol_pid"] > 15, counted
    assert counted["14_tank_farm"] > 10, counted


def test_the_corpus_has_halos_to_check(drawn):
    """Check that the corpus has halos to check."""
    counted = {name: len(halos) for name, (_fs, halos, _bars, _codes) in drawn.items()}
    assert all(counted.values()), counted
    assert counted["11_ethanol_pid"] > 50, counted


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
    assert counted["11_ethanol_pid"] > 80, counted
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
    fs.add_instrument("PI", 1, sensing=riser, at=0.6).annotate(high="PAH", low="PAL")
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
    feed, valve, prod = fs.units[:3]
    feed.pin(port="outlet", x=400, y=500)
    valve.pin(port="inlet", x=480, y=440)
    prod.pin(port="inlet", x=680, y=440)
    fs.add_instrument("TI", 2).annotate(high="TAH", low="TAL").pin(x=300, y=417)
    other, out = fs.add(U.Feed("F2")), fs.add(U.Product("P2"))
    other.pin(port="outlet", x=100, y=429)
    out.pin(port="inlet", x=600, y=330)
    fs.connect(other.outlet, out.inlet).via([(290, 429), (290, 330)])
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
    "a_closed_valve": _codes_beside_a_closed_valve,
    "a_pneumatic_line": _codes_beside_a_pneumatic_line,
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
    assert counted["04_control_loop"] == 2, counted
    assert counted["11_ethanol_pid"] == 6, counted
    assert counted["14_tank_farm"] == 5, counted
