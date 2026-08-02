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

**And a symbol's box is not a symbol's ink**, which is issue #243 and why the
first check below measures the second and not the first.
:func:`~pandid.portgeom.unit_box` reports the geometry; the outline is stroked
*centred* on it, so half the pen lies outside the box and a plate flush against
the box deletes exactly that half. ``examples/14``'s V-604 drew its left shell
wall at 48,7 % of its weight for the forty pixels ``VAP-611-150-40-CS`` ran
beside it -- a 2,06:1 step inside one outline, which ISO 15519-1 §6.2 leaves
nothing to call: "If two or more widths of line are used, the ratio between any
two widths shall be at least 2:1". This file passed on that sheet every time,
because it was asking about the box.
"""

import re

import pytest

from pandid.portgeom import unit_box
from pandid.render.svg import _PLATE_CLEARANCE, _SYMBOL_STROKE, _obstacle

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


@pytest.fixture(scope="module")
def drawn():
    """Every sheet in the corpus, rendered once, as (flowsheet, halos)."""
    out = {}
    for name, build in CORPUS.items():
        fs, kwargs = build()
        svg = fs.to_svg(**{k: v for k, v in kwargs.items() if k in _RENDER_OPTS})
        out[name] = (fs, _halos(svg))
    return out


def _inked(box):
    """A symbol's box grown by the half-pen that is drawn outside it."""
    half = _SYMBOL_STROKE / 2
    return (box[0] - half, box[1] - half, box[2] + half, box[3] + half)


@pytest.mark.parametrize("name", list(CORPUS), ids=list(CORPUS))
def test_no_halo_lands_on_a_graphical_symbol(drawn, name):
    """Measured against the ink, not against the box it is centred on (#243)."""
    fs, halos = drawn[name]
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
    fs, halos = drawn[name]
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


def test_the_corpus_has_halos_to_check(drawn):
    """The check above is vacuous on a sheet that draws no halo, and every one of
    them is read out of the rendered SVG by a regular expression that a change to
    the emitted markup could quietly stop matching."""
    counted = {name: len(halos) for name, (_fs, halos) in drawn.items()}
    assert all(counted.values()), counted
    assert counted["11_ethanol_pid"] > 50, counted
