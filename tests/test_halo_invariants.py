"""What an opaque halo may and may not delete, over the whole shipped corpus.

**No halo breaks a graphical symbol.**

Every piece of text this package writes over the drawing -- an equipment tag, a
line number -- is drawn on a white rectangle so the lines beneath it do not
strike through the lettering. The rectangle is opaque, and it is emitted after
the artwork, so wherever it lands it deletes what was there. Two passes place
one, and each was told about some of the sheet and not all of it: the equipment
tag stepped clear of pipe and impulse lines (:meth:`SvgRenderer._tag_item`) and
the line number stepped clear of those and of the tags
(:meth:`SvgRenderer._draw_streams`), and neither of them ranked a *symbol* above
either.

The difference matters and is not a matter of degree. A line broken by a halo is
still that line: a reader reads across the gap, which is the whole reason
writing a number *in* its run is a convention at all. A symbol broken by a halo
has stopped being the symbol, because its outline is what identifies it --
ISO 15519-2 draws a field instrument as a plain circle and a shared display as a
circle inside a square, and the difference between those two readings *is* the
outline. A bite out of one is not a tag sitting on top of a balloon, it is a
shape that is not in the standard, and a reader is entitled to take it for a
fault in the drawing.

Both defects this file was written for were on ``11_ethanol_pid``, the sheet the
README leads with: D-301's tag ate the upper-left quadrant of LT-304's balloon
and broke its circle in two places, and HV-301C's ate the left edge of
PIC-301's square. Every test in the suite passed, because nothing had ever
looked.

**And no halo breaks an impulse line**, which is issue #223. That is a weaker
statement than the one above and is worth having for a different reason: a line
broken by a halo is still that line, which is why a stream label is allowed to
sit *in* the run it names, but an impulse line is two centimetres of tubing that
exists only to say where a transmitter measures, and ISO 15519-2 §5.1.1 (p. 7)
makes the connection between a PCI symbol and the process a *shall* -- what
passes between the process system and the control system is represented within
the PCI symbol. Delete a
length of one and the sheet has stopped saying it. :func:`~pandid.render.svg._erases`
has ranked impulse lines above pipe since #194, and the defect was that a
valve's fail-position mark never consulted it: ``examples/14``'s XV-601 hangs a
trip square below the valve and fails closed, so PIP PIC001 4.2.4.6(1) put
``FC`` on the same face the square's line leaves, and the example shipped with
the fail position taken off and a note in words instead.

**And a symbol's box is not a symbol's ink**, which is issue #243 and why the
first check below measures the second and not the first.
:func:`~pandid.portgeom.unit_box` reports the geometry; the outline is stroked
*centred* on it, so half the pen lies outside the box and a plate flush against
the box deletes exactly that half. ``examples/14``'s V-604 drew its left shell
wall at 48,7 % of its weight for the forty pixels ``VAP-611-150-40-CS`` ran
beside it -- a 2,06:1 step inside one outline, which ISO 15519-1 §6.2 leaves
nothing to call: where a drawing uses two or more line widths, any two of them
have to stand at least 2:1 apart. This file passed on that sheet every time,
because it was asking about the box.
"""

import math
import re
from typing import NamedTuple

import pytest

from pandid.portgeom import unit_box
from pandid.render.svg import _EQUIPMENT_STROKE, _PLATE_CLEARANCE, _ink, _obstacle

from test_label_invariants import CORPUS, _RENDER_OPTS

_HALO = re.compile(
    r'<rect x="([-\d.]+)" y="([-\d.]+)" width="([\d.]+)" '
    r'height="([\d.]+)" fill="white" />'
)


def _halos(svg: str) -> "list[tuple[float, float, float, float]]":
    """Every opaque plate a label pass drew, from the drawn sheet.

    Read out of the SVG rather than off the placement code, because what the
    invariant is about is what lands on the paper. The sheet's own background is
    the only other white rect on it and it is emitted before the ``<defs>``, so
    the two label groups are what is left.
    """
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


def _overlaps(a, b) -> bool:
    """Do two rectangles share any area? Touching edge to edge does not count."""
    return a[2] > b[0] and a[0] < b[2] and a[3] > b[1] and a[1] < b[3]


class Face(NamedTuple):
    """One drawn flange face, and the joint it belongs to."""

    box: tuple  # the rectangle this bar's stroke covers
    at: tuple  # the *pair's* centre, which is the joint the pair straddles
    port: object  # the nozzle it stands off


def _flange_bars(fs, kwargs) -> "list[Face]":
    """Every flange face on a sheet.

    The rectangle is derived the way ``SvgRenderer._draw_streams`` strokes it --
    two bars ``FLANGE_GAP`` apart along the run, each ``FLANGE_TICK`` across it
    -- rather than read back out of the SVG, because a face is a plain
    ``<line>`` at the pipe's own pen and nothing in the document tells one from
    a length of pipe.

    The port is recovered from the geometry rather than from the placement's own
    bookkeeping: a mark stands ``FLANGE_STANDOFF`` from one end of the polyline
    and the length of the run from the other, so the nearer end names it, and
    that stays true however the placement is reorganised.
    """
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


@pytest.fixture(scope="module")
def drawn():
    """Every sheet in the corpus, rendered once."""
    out = {}
    for name, build in CORPUS.items():
        fs, kwargs = build()
        svg = fs.to_svg(**{k: v for k, v in kwargs.items() if k in _RENDER_OPTS})
        out[name] = Drawn(fs, _halos(svg), _flange_bars(fs, kwargs))
    return out


def _inked(box):
    """A symbol's box grown by the half-pen that is drawn outside it.

    ``_EQUIPMENT_STROKE`` and not a trimmed symbol's finer pen: this is
    the same conservative half-pen ``_obstacle`` grows every box by,
    whatever class actually drew it (see the comment there), so this
    stays the outer bound production code holds a halo to.
    """
    half = _EQUIPMENT_STROKE / 2
    return (box[0] - half, box[1] - half, box[2] + half, box[3] + half)


@pytest.mark.parametrize("name", list(CORPUS), ids=list(CORPUS))
def test_no_halo_lands_on_a_graphical_symbol(drawn, name):
    """Measured against the ink, not against the box it is centred on (#243)."""
    fs, halos, _bars = drawn[name]
    symbols = [(u, unit_box(u, u.frame)) for u in fs.units if u.frame is not None]
    # A tag written *inside* its own symbol carries no halo at all (see
    # _unit_label_box), so every plate on the sheet belongs outside one.
    broken = [
        f"{u.tag or u.kind} at ({box[0]:.0f}, {box[1]:.0f})"
        for halo in halos
        for u, box in symbols
        if _overlaps(halo, _inked(box))
    ]
    assert not broken, f"{name}: halo over the ink of " + "; ".join(sorted(set(broken)))


@pytest.mark.parametrize("name", list(CORPUS), ids=list(CORPUS))
def test_no_halo_is_written_hard_against_an_outline(drawn, name):
    """Not touching is not the same as clear.

    The check above is the one that says a plate takes nothing away. This is the
    drafting half: a line number set against a vessel wall is a number the
    reader has to pick off the equipment, so the placement search keeps
    :data:`~pandid.render.svg._PLATE_CLEARANCE` of paper outside the ink and
    this asserts the sheet got it. Held apart from the check above so a failure
    says which of the two happened.
    """
    fs, halos, _bars = drawn[name]
    symbols = [(u, unit_box(u, u.frame)) for u in fs.units if u.frame is not None]
    crowded = [
        f"{u.tag or u.kind} at ({box[0]:.0f}, {box[1]:.0f})"
        for halo in halos
        for u, box in symbols
        if _overlaps(halo, _obstacle(box))
    ]
    assert not crowded, f"{name}: halo within {_PLATE_CLEARANCE}u of " + "; ".join(
        sorted(set(crowded))
    )


@pytest.mark.parametrize("name", list(CORPUS), ids=list(CORPUS))
def test_no_halo_lands_on_an_impulse_line(drawn, name):
    """The connection between a balloon and the process it reads (#223).

    Measured off :func:`~pandid.render.svg._ink`, which is the same padded
    rectangle the placement search dodges, so a hit here is a hit there and not
    a difference of a rounding. Pipe is deliberately not measured: a line number
    written in its own run is a convention, and this file is about what a halo
    may *not* take away.
    """
    fs, halos, _bars = drawn[name]
    taps = [line.box for line in _ink(fs) if line.kind == "tap"]
    cut = [
        f"({box[0]:.0f}, {box[1]:.0f})-({box[2]:.0f}, {box[3]:.0f})"
        for halo in halos
        for box in taps
        if _overlaps(halo, box)
    ]
    assert not cut, f"{name}: halo over the impulse line at " + "; ".join(sorted(set(cut)))


def test_the_corpus_has_impulse_lines_to_check(drawn):
    """13 of the 22 sheets draw none at all, so the check above is vacuous
    over most of the corpus and says nothing unless the two sheets that draw
    them in quantity are still in it. Counted as ``_ink`` lines of kind
    ``tap``, which is what the check itself reads."""
    counted = {
        name: sum(1 for line in _ink(fs) if line.kind == "tap")
        for name, (fs, _halos, _bars) in drawn.items()
    }
    assert counted["11_ethanol_pid"] > 15, counted
    assert counted["14_tank_farm"] > 10, counted


def test_the_corpus_has_halos_to_check(drawn):
    """The check above is vacuous on a sheet that draws no halo, and every one of
    them is read out of the rendered SVG by a regular expression that a change to
    the emitted markup could quietly stop matching."""
    counted = {name: len(halos) for name, (_fs, halos, _bars) in drawn.items()}
    assert all(counted.values()), counted
    assert counted["11_ethanol_pid"] > 50, counted


# --- and the same question from the other side: the flange marks --------------


@pytest.mark.parametrize("name", list(CORPUS), ids=list(CORPUS))
def test_no_flange_mark_lands_on_a_symbol_it_is_not_the_joint_for(drawn, name):
    """A flange face is drawn hard against the thing it stands off, and on a
    crowded run the thing it lands on may not be that thing.

    The clearance is ``FLANGE_STANDOFF - FLANGE_GAP / 2``, small on purpose --
    the mark says the joint is *outside* the equipment, so a face that drifted in
    would read as part of the shell. Marking both sides of every valve and
    in-line fitting has moved these off the open approaches to a vessel and into
    the middle of a run: on ``11_ethanol_pid``'s CV-303 station a reducer, a
    control valve and an isolation valve stand within thirty units of each
    other, each contributing two faces, and nothing before this had measured one
    against the artwork beside it.

    **The unit the mark is the joint for is excluded, and that is #243's
    box-versus-ink distinction rather than a hole in the check.** Every other
    unit is weighed against :func:`unit_box` because a bounding box is a safe
    over-estimate of where a symbol is -- a label kept out of the box is kept off
    the artwork whatever the artwork does inside it. For the mark's *own* unit
    the over-estimate is not safe to assert on, because the mark is deliberately
    drawn at that unit's nozzle: ``RB-301``'s bottom nozzles sit 4,5 units up
    inside a box whose lower edge is set by the tube sheet, so both of its drain
    flanges are inside the box and clear of every line in it, correctly. What can
    be said about that unit is said below.
    """
    fs, _halos_, bars = drawn[name]
    symbols = [(u, unit_box(u, u.frame)) for u in fs.units if u.frame is not None]
    over = [
        f"{u.tag or u.kind} at ({box[0]:.0f}, {box[1]:.0f})"
        for face in bars
        for u, box in symbols
        if u is not face.port.owner and _overlaps(face.box, _inked(box))
    ]
    assert not over, f"{name}: flange face over the ink of " + "; ".join(sorted(set(over)))


@pytest.mark.parametrize("name", list(CORPUS), ids=list(CORPUS))
def test_a_flange_mark_is_drawn_on_the_outside_of_its_own_nozzle(drawn, name):
    """The half of the check above that the mark's own unit can still be held to,
    and it is a statement about *direction* rather than about clearance.

    ``FLANGE_STANDOFF`` steps the pair along the run from the nozzle it marks.
    Which way along is the whole of what makes it a joint: stepped outward it
    says the branch is bolted to the shell, stepped inward it is a pair of ticks
    drawn across the vessel. So the mark has to end up further from the middle
    of its unit than its own nozzle is, and that holds whatever the symbol does
    between the two -- which is what lets it be asserted where a clearance
    against :func:`unit_box` could not be.
    """
    from pandid.portgeom import port_point

    fs, _halos_, bars = drawn[name]
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
    """The complaint #256 answered from the label pass's side, asserted from the
    mark's.

    A halo is opaque and drawn after the artwork, so a plate that lands on a
    flange face deletes it and the sheet has stopped saying the joint is bolted.
    :func:`~pandid.render.svg.stream_numbers` seeds every mark as an obstacle for
    exactly that reason; this is the check that it is still doing so, over every
    sheet rather than over the one that prompted it.
    """
    fs, halos, bars = drawn[name]
    hit = [
        f"({face.box[0]:.0f}, {face.box[1]:.0f})"
        for face in bars
        for halo in halos
        if _overlaps(face.box, halo)
    ]
    assert not hit, f"{name}: a halo deletes the flange face at " + "; ".join(sorted(set(hit)))


def test_the_corpus_has_flange_marks_to_check(drawn):
    """Both checks above are vacuous on a sheet that marks no joints, and only
    one sheet in the corpus marks any. If ``11_ethanol_pid`` stops asking for
    them -- or if the corpus stops being *rendered* with the option, which is how
    they were invisible here in the first place -- the two say nothing."""
    counted = {name: len(bars) for name, (_fs, _halos_, bars) in drawn.items()}
    # Two faces per mark, and every equipment nozzle plus both sides of every
    # valve and in-line fitting on the densest sheet in the repo.
    assert counted["11_ethanol_pid"] > 80, counted
    assert all(n % 2 == 0 for n in counted.values()), (
        "a flange is a pair of faces and they are drawn together"
    )


# --- letter codes written outside a symbol ------------------------------------
# The quadrant codes are haloed lettering like a tag, so the checks above already
# hold them off the symbols and the impulse lines. These are the two things they
# are held to that a tag is not.
#
# A tag may be written *in* a run -- that is what its halo is for, and a reader
# reads across the gap -- but a letter code sits in a gap two units wide between
# a balloon and whatever is beside it, and there is no run for a reader to read
# across. So it clears every line on the sheet, pipe and signal alike.
#
# And it is placed before either label pass, which is the whole reason
# :func:`~pandid.render.svg.quadrant_labels` derives itself from the flowsheet:
# the equipment tags and the line numbers are handed the boxes it chose and dodge
# them. If that seeding is ever dropped these go red, and nothing else would.


def _code_boxes(fs) -> "list[tuple[float, float, float, float]]":
    """The halo of every letter code written outside a symbol on this sheet."""
    from pandid.render.svg import _unit_label_box, quadrant_labels

    return [b for b in map(_unit_label_box, quadrant_labels(fs)) if b is not None]


@pytest.mark.parametrize("name", list(CORPUS), ids=list(CORPUS))
def test_no_letter_code_lands_on_a_line(drawn, name):
    """Pipe as well as signal, which is stricter than a tag is held to."""
    fs, _halos_, _bars = drawn[name]
    struck = [
        f"({box[0]:.0f}, {box[1]:.0f}) on {line.kind}"
        for box in _code_boxes(fs)
        for line in _ink(fs)
        if _overlaps(box, line.box)
    ]
    assert not struck, f"{name}: a letter code lies on " + "; ".join(sorted(set(struck)))


@pytest.mark.parametrize("name", list(CORPUS), ids=list(CORPUS))
def test_no_letter_code_lands_on_a_tag_or_a_line_number(drawn, name):
    """Every other plate on the sheet is one of those two; see :func:`_halos`."""
    fs, halos, _bars = drawn[name]
    codes = _code_boxes(fs)
    others = [
        h
        for h in halos
        if not any(all(abs(a - b) < 0.2 for a, b in zip(h, code)) for code in codes)
    ]
    hit = [
        f"({box[0]:.0f}, {box[1]:.0f})"
        for box in codes
        for other in others
        if _overlaps(box, other)
    ]
    assert not hit, f"{name}: a letter code is written over a label at " + "; ".join(
        sorted(set(hit))
    )


def test_the_corpus_has_letter_codes_to_check(drawn):
    """Both checks above say nothing on a sheet that annotates nothing, and the
    corpus is free to change. Six codes on three sheets is what it draws today:
    the two alarms on each of 04's LIC-101, 11's PIC-301, TIC-302 and LIC-304,
    and 14's two level indicators, with a lone PAH on its pressure indicator."""
    counted = {name: len(_code_boxes(fs)) for name, (fs, _h, _b) in drawn.items()}
    assert counted["04_control_loop"] == 2, counted
    assert counted["11_ethanol_pid"] == 6, counted
    assert counted["14_tank_farm"] == 5, counted
