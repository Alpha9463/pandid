"""The width ladder of ISO 10628-1 5.3.1, as ratios rather than as numbers.

``tests/test_line_weight.py`` next door asks whether a stroke *survives* the
transforms between its definition and the page. This file asks the question one
level up: whether the widths a sheet draws on stand to each other the way 5.3.1
says they do, and whether every element the renderer picks a width for has been
put in one of the clause's three classes.

**Ratios, not numbers.** Every assertion below divides one measured width by
another wherever the thing under test *is* a proportion. A test that pinned
``4.0`` and ``2.0`` would go on passing after somebody moved one rung and left
the other where it was, which is exactly the defect #490 fixed: the two were
written ``2`` and ``2.0`` in two places and had drifted into agreement without
anybody deciding they should agree.

Not everything here is a ratio, and it should not be. The floor is an absolute
limit and is checked as one; so are the millimetre widths, the number of rungs,
and the paper a flange pair leaves. Those are the places where a number is the
claim, and a ratio would say nothing.

**Measured off the drawing wherever possible.** Most of what is below renders a
sheet and reads the widths back out of it, rather than importing the ladder and
comparing it with itself. Three tests cannot -- the shape of the ladder, its
tie to the grid module, and the ban on literals are properties of the source
rather than of any one drawing -- and those import inside the function so that
the rest of the file still runs where the module does not exist.
"""

import math
import re
from pathlib import Path

import pytest

from pandid import Flowsheet, units
from pandid.render.svg import FLANGE_GAP
from pandid.render.symbols import ARROWHEAD, MIN_HEAD_CLEARANCE
from pandid.streams import SIGNAL_KINDS
from test_golden import SCENARIOS
from test_line_weight import drawn_pens

#: One drawing unit as a physical width. The grid module ISO 10628-1 5.3.1
#: states its widths against is 2,5 mm and ten drawing units, so a unit is a
#: quarter of a millimetre and the clause's three widths land on 4, 2 and 1
#: units exactly. Restated here rather than imported, so that this file's
#: millimetre readings do not come from the same place as the widths they judge.
UNIT_MM = 0.25

#: The groups a sheet draws its own lines into, as opposed to sheet furniture
#: (the border, the title strip, the tables) and the debugging overlay. 5.3.1 is
#: a rule about the flow diagram, and these are the flow diagram.
_LINE_GROUPS = ("streams", "instrument_taps", "units")

ROOT = Path(__file__).resolve().parent.parent


def _quantised(width: float) -> float:
    """A drawn width, to the precision the artwork is stated to.

    ``scripts/vendor_symbols.py`` writes each stencil's compensated width to
    three decimals, so an outline meant for 2 units reaches the page at
    1.999941 and a trimmed one at 0.999938. Two decimals is finer than that
    rounding and coarser than any difference this file is about -- the rungs
    are a whole unit apart at their closest.
    """
    return round(width, 2)


def _renderer_widths(svg: str) -> "set[float]":
    """Every width the *renderer* chose on this sheet.

    The lines it draws itself, plus one width per symbol: a symbol's outline is
    the rung the renderer put it on, and the finer strokes inside the artwork
    are the stencil's own business (see ``authored_pens`` next door). The
    outline is the heaviest pen in the drawing, which is what ``max`` picks.
    """
    out: "set[float]" = set()
    by_symbol: "dict[str, float]" = {}
    for where, lo, _hi in drawn_pens(svg):
        if where in _LINE_GROUPS:
            out.add(_quantised(lo))
        elif where.startswith("sym_"):
            by_symbol[where] = max(by_symbol.get(where, 0.0), lo)
    return out | {_quantised(w) for w in by_symbol.values()}


def _streams_group(svg: str) -> str:
    """Just the ``<g id="streams">`` the runs are drawn into."""
    start = svg.index('<g id="streams">')
    return svg[start : svg.index("</g>", start)]


def _stream_pens(svg: str) -> "set[float]":
    """The widths the *runs* are drawn at.

    The path elements alone: the flange marks and the pneumatic hatch are
    drawn into the same group and are marks on a run rather than the run.
    """
    return {
        _quantised(float(w))
        for w in re.findall(r'<path [^>]*stroke-width="([\d.]+)"', _streams_group(svg))
    }


def _two_unit_sheet() -> Flowsheet:
    """A vessel with a run into it and a control loop reading it.

    One of each thing the ladder has to tell apart: a material run, an equipment
    outline, an instrument balloon and the signal line between them.
    """
    fs = Flowsheet("ladder")
    feed = fs.add(units.Feed("F"))
    vessel = fs.add(units.Vessel("V-1"))
    product = fs.add(units.Product("P"))
    lt = fs.add(units.Instrument("LT-1"))
    lc = fs.add(units.Instrument("LIC-1"))
    fs.connect(feed.outlet, vessel.inlet)
    fs.connect(vessel.outlet, product.inlet)
    fs.connect(lt.sig_out, lc.sig_in, kind="electric")
    return fs


# --- the shape of the ladder --------------------------------------------------


def test_the_ladder_stands_in_the_ratio_5_3_1_states() -> None:
    """4 : 2 : 1, asserted as three divisions and no absolute width.

    ISO 10628-1 5.3.1 a), b) and c). Each neighbouring pair also has to meet
    ISO 15519-1 6.2's 2:1 on its own, not only the pair at the ends.
    """
    from pandid.render.weights import LineWeight

    main = LineWeight.MAIN_FLOW.width
    equipment = LineWeight.EQUIPMENT.width
    detail = LineWeight.DETAIL.width

    assert main / equipment == pytest.approx(2.0)
    assert equipment / detail == pytest.approx(2.0)
    assert main / detail == pytest.approx(4.0)
    # Three rungs and no fourth: a width can only be chosen by naming one.
    assert len(LineWeight) == 3
    # DETAIL is the floor 5.3.1 sets, so nothing on the ladder is under it.
    assert min(rung.width for rung in LineWeight) == detail


def test_each_rung_is_its_own_multiple_of_the_grid_module() -> None:
    """The ladder is derived, not chosen: 5.3.1 states each width as a multiple
    of the module, and each member's *value* is that multiple.

    Which is what makes the ratio unbreakable by editing one rung -- there is no
    width to edit, only a multiple -- and what ties the drawing units to
    millimetres: the module is 2,5 mm and ten units, so a unit is 0,25 mm and
    the three rungs are 1,0 mm, 0,5 mm and 0,25 mm.
    """
    from pandid.render.weights import M, LineWeight

    assert M * UNIT_MM == pytest.approx(2.5)
    for rung in LineWeight:
        assert rung.width == pytest.approx(rung.value * M)
    assert LineWeight.MAIN_FLOW.width * UNIT_MM == pytest.approx(1.0)
    assert LineWeight.EQUIPMENT.width * UNIT_MM == pytest.approx(0.5)
    assert LineWeight.DETAIL.width * UNIT_MM == pytest.approx(0.25)


def test_every_width_survives_the_formatting_it_is_written_with() -> None:
    """``:g`` is how a width reaches the sheet, and ``:g`` rounds.

    ``f"{7.123456789:g}"`` is ``"7.12346"``. Every rung and every width derived
    from one happens to be exactly representable in six significant figures, so
    nothing is lost today -- but that is a property of these numbers and not of
    the formatting, and a rung chosen later need not have it. Checked rather
    than assumed: each width is written the way the renderer writes it and read
    back, and has to be the number it started as.
    """
    from pandid.render.svg import HOP_R, _ink_pad
    from pandid.render.weights import LineWeight

    widths = [rung.width for rung in LineWeight]
    widths += [HOP_R, MIN_HEAD_CLEARANCE] + [_ink_pad(rung) for rung in LineWeight]
    for width in widths:
        assert float(f"{width:g}") == width, (
            f"{width!r} is written as {f'{width:g}'!r} and read back as "
            f"{float(f'{width:g}')!r}, so the sheet does not draw what the "
            f"ladder says"
        )


def test_neither_backend_writes_a_stroke_width_as_a_literal() -> None:
    """The ladder cannot be routed around, which is the half of #490 that a
    number on its own would not have fixed.

    A rung is a decision about what an element *is*, and a decision skipped is
    how a main flow line came to be drawn at the weight of the vessel it enters.
    So neither renderer may write a width down: every ``stroke-width`` and every
    ``strokeWidth`` has to be interpolated from something, and the only things
    there are to interpolate are the three rungs and the arithmetic on them.

    Symbol artwork is not searched. A stencil states its own widths inside its
    own coordinate space and the renderer compensates them (#305); what the
    ladder settles for a symbol is which rung its outline is drawn on, and that
    is chosen in the two files below.
    """
    # What the renderers *emit*, which is the check that cannot be worked
    # around: a literal reaches the sheet whether it was typed as
    # ``stroke-width="2"`` or as ``stroke-width="{2}"``, and only one of those
    # is visible to a source scan.
    bad: "list[str]" = []
    corpus = {
        name: _renderer_widths(build().to_svg(**kw)) for name, (build, kw) in SCENARIOS.items()
    }
    rungs: "set[float]" = set().union(*corpus.values())
    if len(rungs) > 3:
        bad.append(
            f"the corpus draws {len(rungs)} widths, {sorted(rungs)}, and the ladder has three rungs"
        )
    for name, widths in corpus.items():
        for width in widths - rungs:
            bad.append(
                f"{name}: the sheet drew a {width:g}-unit line, "
                f"which is no rung the rest of the corpus draws on"
            )
    # ...and the source scan as well, which catches a literal in a branch no
    # corpus sheet happens to take. Any digit inside the value, not only one
    # against the quote.
    for name in ("svg.py", "drawio.py"):
        text = (ROOT / "pandid" / "render" / name).read_text(encoding="utf-8")
        for n, line in enumerate(text.splitlines(), 1):
            # A substitution that *rewrites* a width the stencil already
            # declared is not a width being chosen -- it is #305's artwork
            # compensation, whose digits are a format spec and a capture
            # group. Named narrowly, so a real literal cannot hide behind it.
            if "m.group(" in line:
                continue
            if re.search(r'stroke-width="[^"]*\d', line) or re.search(
                r"strokeWidth=[^;\"']*\d", line
            ):
                bad.append(f"pandid/render/{name}:{n}: {line.strip()}")
    assert not bad, "a width written as a literal instead of chosen from the ladder:\n" + "\n".join(
        bad
    )


# --- the ladder as the sheet draws it -----------------------------------------


def test_a_main_flow_line_is_drawn_at_twice_the_equipment_it_enters() -> None:
    """#490 itself. A main flow line is 5.3.1 a) and the vessel it runs into is
    5.3.1 b), and the clause exists so that the first stands out from the
    second; drawn at one weight, it does not.

    Measured as the ratio between the two pens the sheet actually put down, so
    it says nothing about either number and everything about the pair.
    """
    fs = _two_unit_sheet()
    svg = fs.to_svg()
    run = max(_stream_pens(svg))
    outline = _quantised(
        max(lo for where, lo, _hi in drawn_pens(svg) if where.startswith("sym_vessel"))
    )
    assert run / outline == pytest.approx(2.0)


def test_a_control_line_is_drawn_at_a_quarter_of_the_run_it_reads() -> None:
    """5.3.1 c) against a), the two ends of the ladder, on one sheet.

    A signal line and an impulse tap are the same rung as each other and a
    quarter of the run -- which is the whole of what tells a reader the
    instrumentation from the process.
    """
    fs = _two_unit_sheet()
    svg = fs.to_svg()
    pens = sorted(_stream_pens(svg))
    assert len(pens) == 2, f"expected a run and a signal, got {pens}"
    signal, run = pens
    assert run / signal == pytest.approx(4.0)


@pytest.mark.parametrize("name", list(SCENARIOS), ids=list(SCENARIOS))
def test_every_width_a_sheet_draws_on_is_a_rung_of_one_ladder(name: str) -> None:
    """Over the whole corpus: the widths the renderer chose, divided by the
    finest of them, are whole powers of two and no more than three of them.

    A fourth width, or a rung at 1,5 times another, fails here without this file
    knowing what any rung is worth -- so a sheet cannot be brought into line by
    moving the target.
    """
    build, kwargs = SCENARIOS[name]
    widths = _renderer_widths(build().to_svg(**kwargs))
    assert widths, f"{name} drew nothing"
    finest = min(widths)
    steps = sorted(w / finest for w in widths)
    assert all(math.isclose(s, round(s), rel_tol=1e-9) for s in steps), (
        f"{name}: widths {sorted(widths)} are not whole multiples of {finest}"
    )
    assert all(round(s) in (1, 2, 4) for s in steps), (
        f"{name}: widths {sorted(widths)} stand at {steps} of each other, "
        f"which is not the 4:2:1 of ISO 10628-1 5.3.1"
    )
    assert len(widths) <= 3, f"{name}: {len(widths)} widths, and 5.3.1 states three"


@pytest.mark.parametrize("name", list(SCENARIOS), ids=list(SCENARIOS))
def test_no_line_the_renderer_chooses_a_width_for_is_under_the_floor(name: str) -> None:
    """ISO 10628-1 5.3.1's floor, in the units the sheet is drawn in.

    The floor is the finest rung itself, so this is the statement that nothing
    the renderer picks a width for sits below the rung it would have been given
    had it been put in the finest class. Read as a millimetre as well, since the
    floor is stated as one and a ratio cannot express it.
    """
    build, kwargs = SCENARIOS[name]
    for width in _renderer_widths(build().to_svg(**kwargs)):
        assert width * UNIT_MM >= 0.25 - 1e-9, (
            f"{name}: a line drawn at {width:g} units is {width * UNIT_MM:.3f} mm, "
            f"under the floor ISO 10628-1 5.3.1 sets"
        )


# --- the same ladder in the other backend -------------------------------------


@pytest.mark.parametrize("name", list(SCENARIOS), ids=list(SCENARIOS))
def test_the_export_puts_every_run_on_the_rung_the_sheet_puts_it_on(name: str) -> None:
    """A ``.drawio`` file is the same drawing, run for run.

    The cross-backend half is held as a ratio, because the export scales every
    width through the sheet fit: on a paged sheet the two backends' figures
    differ by design and their *proportions* may not. So each run's exported
    width is divided by the width the sheet drew it at, and all of those
    quotients have to be the one fit.

    **Agreement is not enough on its own**, and this test used to stop there:
    two backends that had both collapsed to the finest rung would have agreed
    perfectly. So the sheet's own widths are pinned absolutely first -- a run
    is 4 units, a control line is 1 -- and the parity check runs on top of a
    drawing already known to be right.
    """
    from test_drawio import _DRAWIO_KWARGS, _drawio_cells, _style

    build, kwargs = SCENARIOS[name]
    fs = build()
    drawn = [
        float(w)
        for w in re.findall(
            r'<path [^>]*stroke-width="([\d.]+)"', _streams_group(fs.to_svg(**kwargs))
        )
    ]
    cells = _drawio_cells(build(), {k: v for k, v in kwargs.items() if k in _DRAWIO_KWARGS})
    exported = [
        float(_style(cells[f"s{n}"])["strokeWidth"])
        for n in range(len(drawn))
        if f"s{n}" in cells and "strokeWidth" in _style(cells[f"s{n}"])
    ]
    assert len(exported) == len(drawn) > 0, (
        f"{name}: the sheet drew {len(drawn)} runs and the export wrote {len(exported)}"
    )
    # The positive half: the numbers themselves, per stream, from the model
    # rather than from the renderer's own answer about the same stream.
    for stream, width in zip(fs.streams, drawn):
        want = 1.0 if stream.kind in SIGNAL_KINDS else 4.0
        assert width == pytest.approx(want), (
            f"{name}: {stream.name or stream.kind} is a "
            f"{'control or data line' if stream.kind in SIGNAL_KINDS else 'material run'} "
            f"and the sheet drew it at {width:g}, not {want:g}"
        )
    fits = [e / d for e, d in zip(exported, drawn)]
    assert max(fits) / min(fits) == pytest.approx(1.0, rel=1e-3), (
        f"{name}: the two backends put some run on different rungs -- "
        f"exported/drawn ranges over {min(fits):.4g} to {max(fits):.4g}"
    )


# --- the clearances a width has to leave --------------------------------------


def test_a_flange_pair_leaves_the_paper_5_3_2_asks_between_two_parallel_lines() -> None:
    """The two faces of a flange are two parallel lines a fixed distance apart,
    so which rung they are drawn on is settled by arithmetic and not by taste.

    ISO 10628-1 5.3.2 puts the floor at twice the wider of the two and at 1 mm.
    The pair is ``FLANGE_GAP`` apart centre to centre, so at a width w they
    leave ``FLANGE_GAP - w`` -- which clears both floors on 5.3.1 c)'s rung and
    on no heavier one.
    """
    fs = Flowsheet("flanges")
    vessel = fs.add(units.Vessel("V-1"))
    pump = fs.add(units.Pump("P-1"))
    product = fs.add(units.Product("P"))
    fs.connect(vessel.outlet, pump.suction)
    fs.connect(pump.discharge, product.inlet)
    svg = _streams_group(fs.to_svg(diagram="p&id", connections="flanged"))
    bars = re.findall(r'<line [^>]*stroke-width="([\d.]+)" />', svg)
    assert bars, "the sheet drew no flange mark"
    width = max(float(b) for b in bars)
    gap = FLANGE_GAP - width
    assert gap >= 2 * width - 1e-9, (
        f"two {width:g}-unit faces {gap:g} apart, and 5.3.2 asks {2 * width:g}"
    )
    assert gap * UNIT_MM >= 1.0 - 1e-9, (
        f"two flange faces {gap * UNIT_MM:.2f} mm apart, and 5.3.2 asks 1 mm"
    )


def test_the_arrowhead_clearance_floor_is_twice_the_line_the_heads_end() -> None:
    """``MIN_HEAD_CLEARANCE`` is the same 5.3.2 floor applied to two arrowheads
    side by side on one face, and it has to track the rung those heads end.

    This passed before #490 as well, and is here because that is the accident it
    guards: the floor was written ``2 * 2.0`` beside a main flow line that was
    itself 2 units, so the two agreed by coincidence rather than by derivation
    and a rung moving would have left the floor at half the clause's figure.
    """
    fs = _two_unit_sheet()
    run = max(_stream_pens(fs.to_svg()))
    assert MIN_HEAD_CLEARANCE == pytest.approx(2 * run)


def test_a_leader_head_is_a_size_and_does_not_follow_a_rung() -> None:
    """A leader ends in a head half the flow head's size -- and the line it ends
    is a *quarter* of a main flow line, not a half.

    The two used to be one number: the head was written as the flow head times
    the ratio between two rungs, which read correctly only while that ratio was
    2:1. It is 4:1 now, and a head that had followed it would have halved
    without anything in the drawing asking it to. A width and a size are
    different quantities, and this is the assertion that they have come apart.
    """
    from pandid.render.svg import _LEADER_HEAD

    fs = _two_unit_sheet()
    pens = sorted(_stream_pens(fs.to_svg()))
    assert ARROWHEAD / _LEADER_HEAD == pytest.approx(2.0)
    assert pens[-1] / pens[0] == pytest.approx(4.0)
