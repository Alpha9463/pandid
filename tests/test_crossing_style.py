"""Which mark a crossing carries is the author's choice (#499).

Three conventions, and the documents on disk do not agree between them:
ISO 10628-1 5.3.4 interrupts one of the two lines, ISO 15519-1 12.5 Figure 31
draws both straight through, and the semicircular bridge pandid has always
drawn is in neither. ``crossing_style`` offers all three, and the default is
the interruption 5.3.4 asks for: 4.1 puts block diagrams, PFDs and P&IDs alike
under Clause 5, so the rule does not vary by diagram type and the package
should not either. The bridge stays available for a house style that wants it.

What this file holds, and what it deliberately does not:

* **The default is a named constant, not a word.** Byte equality against the 21
  goldens is ``tests/test_golden.py``'s job and is not restated here; what is
  restated is that *naming* the default draws the same bytes as not naming it,
  on both backends, on every corpus sheet that has a crossing to draw. The
  cases say ``CROSSING_STYLE_DEFAULT`` rather than the word it currently holds,
  so they keep saying the same thing the next time it changes.
* **Each style draws its own mark and nothing else.** Measured against the
  same run drawn with nothing crossing it, so ``"plain"`` cannot pass by
  drawing something else that happens not to be an arc.
* **The two backends mark the same runs.** Divergence is a failure, not a
  finding: an export that hops what the sheet interrupts says the drawing is
  something it is not.
* **An unknown spelling raises, and a known one is handed on.** Accepted-and-
  ignored is the failure mode this option is written against, and it is the
  one ``jump_direction`` beside it was fixed for in #481. Both halves are
  checked here: the word is refused at every call that takes it, *and* every
  call that takes it passes it down -- ``render()`` accepting the keyword and
  dropping it on the way to ``to_svg()`` is the same swallowing wearing a
  different hat, and is what this file caught during the writing of it.
* **``crossing-unmarked`` follows the style.** The finding exists since #490;
  what is new is that it names the mark the sheet was drawing and falls silent
  under ``"plain"``, which drew every crossing exactly as it said it would.

It does **not** hold that the interruption is legible everywhere. It is not:
the break comes out of the run, so a crossing near a corner leaves a short
stub. That is measured on #499 and stays #498's to fix in the router; the
deliverable here is the choice, and the docstrings say what choosing it costs.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import xml.etree.ElementTree as ET

import pytest

from pandid import Flowsheet, spec, units as U
from pandid.cli import EXIT_OK, EXIT_USAGE, main
from pandid.geometry import Route
from pandid.render.drawio import _JUMP_STYLES, DrawioRenderer
from pandid.render.svg import (
    CROSSING_STYLE_DEFAULT,
    CROSSING_STYLES,
    CROSSING_UNMARKED,
    HOP_R,
    SvgRenderer,
    check_crossing_style,
    stream_polyline,
    unmarked_crossings,
)

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _gallery():
    path = ROOT / "scripts" / "gallery.py"
    found = importlib.util.spec_from_file_location("_pandid_script_gallery_x", path)
    assert found is not None and found.loader is not None
    module = importlib.util.module_from_spec(found)
    found.loader.exec_module(module)
    return module


gallery = _gallery()

#: The shipped sheets that have a crossing on them at all, so no case below
#: passes by having nothing to draw. Asserted rather than trusted: each case
#: checks its sheet really does mark something before it compares anything.
MARKED = (
    "08_from_data",
    "11_ethanol_pid",
    "15_condensing_turbine",
    "16_demineralised_water",
    "17_stirred_reactor_train",
    "18_fixed_bed_recycle",
    "19_absorber_stripper",
    "20_molecular_sieve_dryer",
    "21_alumina_refinery",
)

#: The shipped sheets with a crossing too near a corner to carry any mark, and
#: how many each has. #490 found and reported them; this file holds that the
#: report follows ``crossing_style`` rather than assuming the arc. It was two
#: sheets until #483 taught the router to charge for a crossing, which routed
#: one of them away; then one until the main-flow rung came back to the weight
#: of the equipment, which shrank ``HOP_R`` -- the radius is the hop's clearance
#: plus a pen, so a narrower pen needs less run either side of a crossing to
#: carry its mark, and 19_absorber_stripper's last bare crossing now fits one.
#: The number is measured, not assumed, and
#: ``test_the_corpus_leaves_exactly_two_crossings_bare`` re-measures it.
BARE: "dict[str, int]" = {}

#: The keywords the draw.io backend takes, from the ones a gallery sheet is
#: drawn with. The same filter ``tests/test_drawio.py`` applies.
_DRAWIO_KWARGS = (
    "diagram",
    "page_size",
    "border",
    "show_stream_table",
    "connections",
    "jump_direction",
)

_ARC = f"A {HOP_R:g} {HOP_R:g} 0 0 1 "


# --- reading a drawn sheet ----------------------------------------------------


def _paths(svg: str) -> list[str]:
    """Every **run** in the ``streams`` group, as its ``d``, in stream order.

    ``fill="none"`` is what tells a run from the other path the group
    contains: a line number sent away on a leader draws a filled arrowhead,
    which is part of the label rather than a run and would otherwise be
    counted as one.
    """
    group = svg.split('<g id="streams">', 1)[1].split("</g>", 1)[0]
    return re.findall(r'<path d="(M [^"]*)" fill="none"', group)


def _marks(svg: str) -> tuple[int, int]:
    """``(arcs, breaks)`` over the runs: sweeps and second subpaths."""
    paths = _paths(svg)
    return (sum(d.count(_ARC) for d in paths), sum(d.count("M ") - 1 for d in paths))


def _jumps(document: str) -> dict[str, str]:
    """``{cell id: jumpStyle}`` for every edge in an export that carries one."""
    root = ET.fromstring(document).find("diagram/mxGraphModel/root")
    assert root is not None
    out = {}
    for cell in root.iter("mxCell"):
        style = dict(
            part.split("=", 1)  # pyright: ignore[reportArgumentType]
            for part in (cell.get("style") or "").split(";")
            if "=" in part
        )
        if style.get("jumpStyle", "none") != "none":
            out[cell.get("id") or ""] = style["jumpStyle"]
    return out


def _edge_order(document: str) -> list[str]:
    """The ids of the stream edges, in the order the file writes them."""
    root = ET.fromstring(document).find("diagram/mxGraphModel/root")
    assert root is not None
    return [
        cell.get("id") or ""
        for cell in root.iter("mxCell")
        if cell.get("edge") == "1" and re.fullmatch(r"s\d+", cell.get("id") or "")
    ]


def _found(fs) -> list:
    return [w for w in fs.warnings if w.code == CROSSING_UNMARKED]


# --- two runs that cross, built to order --------------------------------------


def _pair(bend: float | None = None) -> Flowsheet:
    """One horizontal run and one vertical pair crossing it, twice.

    ``bend`` is where the vertical run turns back. ``None`` leaves the two
    runs straight and gives a sheet with **no** crossing at all, which is what
    ``"plain"`` is measured against: a run drawn plain through a crossing has
    to come out as the run that had nothing to cross.

    The waypoints are set on the route rather than through ``via()`` because
    the router keeps a corner six units clear of another run and this needs
    one four units clear of it. What is under test is the renderer's crossing
    pass, and the geometry it is given is the fixture; the router's own
    clearance is #498's and is not what these cases are about.
    """
    fs = Flowsheet("crossing")
    a = fs.add(U.Feed("F1")).pin(x=60, y=175)
    b = fs.add(U.Product("P1")).pin(x=600, y=175)
    c = fs.add(U.Feed("F2")).pin(x=60, y=375)
    d = fs.add(U.Product("P2")).pin(x=600, y=375)
    fs.connect(a.outlet, b.inlet)
    run = fs.connect(c.outlet, d.inlet)
    fs.layout()
    fs.route()
    fs.renumber_streams()
    if bend is not None:
        run.route = Route(waypoints=[(300.0, 375.0), (300.0, bend), (400.0, bend), (400.0, 375.0)])
    return fs


#: A crossing with room for any of the three marks: the vertical run turns
#: back 75 units above the line it crosses, against the ``HOP_R`` the mark
#: needs.
ROOMY = 100.0
#: The same crossing four units from the corner, which is under ``HOP_R``, so
#: no mark fits and the sheet has to draw it bare and say so.
TIGHT = 171.0


def _svg(fs: Flowsheet, **opts) -> str:
    return SvgRenderer().render(fs, **opts)


def _drawio(fs: Flowsheet, **opts) -> str:
    return DrawioRenderer().render(fs, **opts)


# --- the default ---------------------------------------------------------------


@pytest.mark.parametrize("stem", MARKED, ids=MARKED)
def test_naming_the_default_draws_what_not_naming_it_draws(stem):
    """Naming the default draws what leaving it unnamed draws, to the byte.

    Stated against the constant rather than against a word, so it keeps
    saying the same thing when the default changes -- as it did when the
    interruption ISO 10628-1 5.3.4 asks for replaced the arc.

    The goldens hold the *bytes*; this holds that the new keyword is a no-op
    at its default, which is the half of "nothing changes" a golden cannot
    state -- a golden compares one render against a file and would pass just
    as happily if the keyword were dropped on the way through.

    Both backends, and only on sheets that have a crossing to draw, which is
    asserted rather than assumed: on a sheet with none the two renders agree
    whatever the keyword does.
    """
    fs, kwargs = gallery.flowsheet(stem)
    default = fs.to_svg(**kwargs)
    assert sum(_marks(default)) > 0, f"{stem} has no crossing and proves nothing"
    fs, kwargs = gallery.flowsheet(stem)
    assert fs.to_svg(**kwargs, crossing_style=CROSSING_STYLE_DEFAULT) == default

    export = {k: v for k, v in kwargs.items() if k in _DRAWIO_KWARGS}
    fs, kwargs = gallery.flowsheet(stem)
    fs.to_svg(**kwargs)
    plain_call = fs.to_drawio(**export)
    assert _jumps(plain_call), f"{stem} exports no jump and proves nothing"
    fs, kwargs = gallery.flowsheet(stem)
    fs.to_svg(**kwargs)
    assert fs.to_drawio(**export, crossing_style=CROSSING_STYLE_DEFAULT) == plain_call


# --- what each style draws ------------------------------------------------------


def test_each_style_draws_its_own_mark_and_nothing_else():
    """Two crossings, three styles, measured against the run with nothing
    crossing it.

    ``"plain"`` is the one that needs the comparison: "no arc" is satisfied by
    any number of wrong drawings, and what it has to be is the path the run
    would have had if the other line were not there. So the fixture is built a
    second time straight, and the marking run's ``d`` is held to it.
    """
    arc = _svg(_pair(ROOMY), crossing_style="arc")
    gap = _svg(_pair(ROOMY), crossing_style="gap")
    plain = _svg(_pair(ROOMY), crossing_style="plain")

    assert _marks(arc) == (2, 0), "the arc bridges both crossings in one subpath"
    assert _marks(gap) == (0, 2), "the interruption breaks the run at both"
    assert _marks(plain) == (0, 0), "a plain crossing marks neither"

    # The run drawn through a crossing plainly is the run that had none.
    straight = _paths(_svg(_pair(None)))
    turned = [d for d in _paths(plain) if "300" in d]
    assert len(turned) == 1
    assert turned[0].count("L ") == 5, "the vertical run keeps all five legs"
    assert _ARC not in turned[0] and turned[0].count("M ") == 1
    assert len(straight) == len(_paths(plain))


def test_the_mark_takes_the_same_run_whichever_mark_it_is():
    """The arc and the interruption span one length of run, ``2 * HOP_R``.

    That is what lets one room test serve all three styles, and what keeps a
    sheet redrawn in the other convention from needing anything else to move.
    It is asserted on the coordinates rather than on the constant: the arc's
    two ends and the interruption's two ends are the same four numbers.
    """
    arc_run = [d for d in _paths(_svg(_pair(ROOMY), crossing_style="arc")) if _ARC in d][0]
    gap_run = [d for d in _paths(_svg(_pair(ROOMY), crossing_style="gap")) if d.count("M ") > 1][0]
    # The point each command ends at, whichever command it is.
    point = re.compile(r"[LMA][^LMA]*?([\d.]+),([\d.]+)")
    arc_points = point.findall(arc_run)
    assert arc_points == point.findall(gap_run), (
        "the two marks end at the same points, so the run they take out is "
        "the same run and a sheet redrawn in the other convention needs "
        "nothing else to move"
    )
    # ...and that run is HOP_R either side of the crossing.
    ys = {float(y) for x, y in arc_points if float(x) == 300.0}
    assert {175.0 - HOP_R, 175.0 + HOP_R} <= ys


def test_the_interruption_leaves_one_line_and_not_two():
    """A break is a second subpath of the same ``d``, not a second element.

    Two elements would double the run in anything reading the file back, and
    would take the arrowhead with them: ``marker-end`` lands on the last
    subpath, so an interrupted run keeps its head where an interrupted
    *element* would have put one at the break.
    """
    fs = _pair(ROOMY)
    gap = _svg(fs, crossing_style="gap")
    assert len(_paths(gap)) == len(_paths(_svg(_pair(ROOMY))))
    broken = [d for d in _paths(gap) if d.count("M ") > 1][0]
    run = stream_polyline(fs.streams[1])
    assert broken.startswith(f"M {run[0][0]},")
    assert broken.endswith(f"L {run[-1][0]},{run[-1][1]}"), (
        "the last command is the run reaching its own end, so marker-end "
        "lands there and not at the break"
    )


# --- both backends --------------------------------------------------------------


@pytest.mark.parametrize("style", CROSSING_STYLES, ids=CROSSING_STYLES)
@pytest.mark.parametrize("stem", MARKED, ids=MARKED)
def test_the_export_marks_the_runs_the_sheet_marks_and_marks_them_alike(stem, style):
    """The two backends draw one drawing.

    A hop in the file where the sheet interrupts, or an arc where the sheet
    draws nothing, is a document that says the piping is something it is not
    -- the same class of error as a hop the wrong way round, which
    ``tests/test_drawio.py`` already treats as a hard failure.

    Three things are held: the *set* of runs that carry a mark is inside the
    set the sheet marked, the ``jumpStyle`` on each is the one this style maps
    to, and at ``"plain"`` there is no style on any edge **and no edge has
    moved** -- the export reorders edges only to let draw.io draw a jump, so a
    sheet with no jump must come out in stream order.
    """
    fs, kwargs = gallery.flowsheet(stem)
    # One path per stream, in ``fs.streams`` order, which is the order the
    # export names them ``s0..``. See :meth:`SvgRenderer._draw_streams`.
    paths = _paths(fs.to_svg(**kwargs, crossing_style=style))
    assert len(paths) == len(fs.streams)
    marked = {n for n, d in enumerate(paths) if _ARC in d or d.count("M ") > 1}
    export = {k: v for k, v in kwargs.items() if k in _DRAWIO_KWARGS}
    document = fs.to_drawio(**export, crossing_style=style)
    jumps = _jumps(document)

    if style == "plain":
        assert not jumps, f"{stem}: plain crossings, and the export hops anyway"
        assert not marked, f"{stem}: plain crossings, and the sheet marked one"
        order = _edge_order(document)
        assert order == sorted(order, key=lambda i: int(i[1:])), (
            f"{stem}: nothing hops, so nothing had to be written after "
            f"anything, and the edges must come out in stream order"
        )
        return

    assert marked, f"{stem}: no run marked, so this case proves nothing"
    assert set(jumps) <= {f"s{n}" for n in marked}, (
        f"{stem}: the export marks {sorted(set(jumps))}, the sheet marks "
        f"{sorted(f's{n}' for n in marked)} -- a mark the sheet does not draw "
        f"states the wrong pipe passes over"
    )
    assert set(jumps.values()) == {_JUMP_STYLES[style]}, (
        f"{stem}: exported as {sorted(set(jumps.values()))}, drawn as {style}"
    )


def test_the_export_writes_one_jump_size_for_either_mark():
    """draw.io reads the half-extent off ``jumpSize`` before it branches on
    the style, so the arc and the gap are one number and the export does not
    have to solve it twice."""
    fs = _pair(ROOMY)
    arc = _drawio(fs, crossing_style="arc")
    gap = _drawio(fs, crossing_style="gap")
    sizes = [set(re.findall(r"jumpSize=(\d+)", doc)) for doc in (arc, gap)]
    assert sizes[0] and sizes[0] == sizes[1]
    assert arc.replace("jumpStyle=arc", "jumpStyle=gap") == gap, (
        "the style is the only thing that differs between the two exports"
    )


# --- the value is checked -------------------------------------------------------


@pytest.mark.parametrize("bad", ["", "none", "Arc", "hop", "break", "arcs", "gap "])
def test_an_unknown_crossing_style_is_refused_and_names_what_is_accepted(bad):
    """Accepted-and-ignored is the failure this option is written against.

    An author who typed ``"break"`` and got the arc has been handed a drawing
    they did not ask for, with nothing in the file or on ``warnings`` to say
    so -- and would find out from a reader. So the word is checked where it is
    given, and the message carries the argument's name, what was typed and
    every spelling that would have worked.
    """
    with pytest.raises(ValueError) as raised:
        check_crossing_style(bad)
    message = str(raised.value)
    assert "crossing_style" in message
    assert repr(bad) in message
    for name in CROSSING_STYLES:
        assert repr(name) in message


@pytest.fixture
def shown(monkeypatch):
    """``show()`` stopped at the display: the SVG it produced, unshown.

    ``tests/test_show.py``'s own fixture, restated here because a case below
    would otherwise open a window and **block** rather than fail -- which is
    how the missing forwarding this file now guards was first met.
    """
    from pandid.render import preview as P

    seen: dict = {}

    def fake(svg, *, title=""):
        seen["svg"] = svg
        return "window"

    monkeypatch.setattr(P, "preview", fake)
    return seen


@pytest.mark.parametrize("call", ["to_svg", "to_drawio", "render", "show"])
def test_every_call_that_takes_the_word_refuses_a_word_it_cannot_draw(call, tmp_path, shown):
    """Every entry point, not just the one nearest the drawing.

    ``render()`` is the one that matters most: a file written under a spelling
    the library folded to something else is a wrong drawing on disk, so the
    refusal has to come before anything is written.
    """
    fs = _pair(ROOMY)
    out = tmp_path / "sheet.svg"
    with pytest.raises(ValueError, match="crossing_style"):
        if call == "render":
            fs.render(out, crossing_style="hop", check=False)
        elif call == "show":
            fs.show(crossing_style="hop", check=False)
        else:
            getattr(fs, call)(crossing_style="hop", check=False)
    assert not out.exists(), "a refused option must not leave a drawing behind"
    assert not shown, "a refused option must not have been drawn either"


def test_every_entry_point_hands_the_word_on(tmp_path, shown):
    """Taking the keyword is half of it; each call has to pass it down.

    ``render()`` and ``show()`` reach a renderer through ``to_svg()`` /
    ``to_drawio()``, and a keyword added to their signature but not to that
    call is precisely the swallowing this option exists to refuse -- an author
    gets the default drawing and nothing says so. Caught here rather than by a
    reader noticing the sheet came out bridged.
    """
    svg = tmp_path / "sheet.svg"
    drawio = tmp_path / "sheet.drawio"
    _pair(ROOMY).render(svg, crossing_style="arc", check=False)
    assert svg.read_text(encoding="utf-8") == _pair(ROOMY).to_svg(crossing_style="arc", check=False)
    assert svg.read_text(encoding="utf-8") != _pair(ROOMY).to_svg(check=False), (
        "...and the two really are different drawings, or this proves nothing"
    )
    _pair(ROOMY).render(drawio, crossing_style="arc", check=False)
    assert drawio.read_text(encoding="utf-8") == _pair(ROOMY).to_drawio(
        crossing_style="arc", check=False
    )
    _pair(ROOMY).show(crossing_style="arc", check=False)
    assert shown["svg"] == _pair(ROOMY).to_svg(crossing_style="arc", check=False)


def test_both_renderers_refuse_it_too():
    """The renderers are public and are called directly by the two callers
    that hold them equal, so the check cannot live only on ``Flowsheet``."""
    fs = _pair(ROOMY)
    for renderer in (SvgRenderer(), DrawioRenderer()):
        with pytest.raises(ValueError, match="crossing_style"):
            renderer.render(fs, crossing_style="semicircle")


_SPEC = """\
{"name": "Skid",
 "units": [{"kind": "Feed", "name": "Raw Feed"},
           {"kind": "Pump", "name": "P-101"},
           {"kind": "Product", "name": "To Unit 200"}],
 "streams": [{"from": ["Raw Feed", "outlet"], "to": ["P-101", "suction"]},
             {"from": ["P-101", "discharge"], "to": ["To Unit 200", "inlet"]}]}
"""


def test_the_shell_offers_exactly_the_three_the_api_offers(tmp_path, capsys):
    """``--crossing-style`` reads its choices off the renderer's own tuple, so
    the two cannot drift, and the file it writes is the file the keyword
    writes."""
    spec_file = tmp_path / "sheet.json"
    spec_file.write_text(_SPEC, encoding="utf-8")
    out = tmp_path / "cli.svg"
    argv = ["draw", str(spec_file), "-o", str(out), "--crossing-style", "gap"]
    assert main(argv) == EXIT_OK
    capsys.readouterr()
    assert out.read_text(encoding="utf-8") == spec.from_json(spec_file).to_svg(crossing_style="gap")
    assert main(["draw", str(spec_file), "-o", str(out), "--crossing-style", "hop"]) == EXIT_USAGE


def test_the_model_does_not_carry_the_crossing_style():
    """A render option and not a property of the plant, exactly as
    ``jump_direction`` is.

    ``to_dict()`` is the flowsheet's topology and the same drawing rendered
    two ways is one flowsheet, so neither word belongs in it -- and the spec
    reader refuses one written there rather than reading it and losing it.
    """
    fs = _pair(ROOMY)
    before = fs.to_dict()
    fs.to_svg(crossing_style="gap", check=False)
    assert fs.to_dict() == before
    assert "crossing_style" not in repr(before)
    assert "jump_direction" not in repr(before)
    with pytest.raises(spec.SpecError, match="crossing_style"):
        spec.from_dict({**before, "crossing_style": "gap"})


# --- a crossing that cannot carry its mark --------------------------------------


@pytest.mark.parametrize("style", ["arc", "gap"])
def test_a_crossing_with_no_room_for_its_mark_is_reported(style):
    """A crossing nearer than ``HOP_R`` to the end of its own segment has no
    run to draw a mark into, so both backends drop it.

    The finding is #490's; what #499 adds is that it follows the style. A bare
    crossing on a sheet that marks its others does not read as "no
    information": it reads as a junction, which is a statement about the
    piping and a false one.
    """
    fs = _pair(TIGHT)
    svg = _svg(fs, crossing_style=style)
    assert _marks(svg) == (0, 0), "no mark fits, so none is drawn"
    findings = _found(fs)
    assert len(findings) == 2, "two crossings drawn bare, two said out loud"
    mark = "arc" if style == "arc" else "interruption"
    for finding in findings:
        assert finding.severity == "warning"
        assert "S1" in finding.message and "S2" in finding.message
        assert "175" in finding.message, "the point a reader has to go and look at"
        assert f"the {mark} marking a crossing" in finding.message, (
            "the finding names the mark the sheet was drawing, not the arc"
        )
        assert "via()" in finding.message, "and what to do about it"
        assert "crossing_style='plain'" in finding.message, (
            "...including the cure #499 made available"
        )


def test_a_plain_sheet_reports_nothing_because_it_promised_nothing():
    """``"plain"`` draws every crossing bare on purpose, so a finding against
    each would be a finding against the option rather than the drawing.

    The fixture carries the whole of this now. It used to be held on the
    shipped sheets as well, so that it could not pass by there being nothing to
    report -- but ``BARE`` is empty since the main-flow rung came back to the
    weight of the equipment, and a loop over an empty table asserts nothing. So
    the fixture is checked *both* ways instead: it has to report at the default
    style before ``"plain"`` is allowed to silence it, which is the same guard
    the shipped sheets were giving.
    """
    fs = _pair(TIGHT)
    _svg(fs)
    assert _found(fs), (
        "the fixture reports nothing at the default style, so the assertion "
        "below would pass on a sheet that had nothing to silence"
    )
    _svg(fs, crossing_style="plain")
    assert not _found(fs)


def test_the_finding_counts_the_crossings_the_sheet_left_bare():
    """The report and the drawing are held to each other rather than each to
    its own idea of the sheet.

    Crossings on the sheet, minus marks actually drawn, is what has to be
    reported -- computed here from the ink and from the model separately, the
    way ``test_a_hop_has_room_for_its_own_arc`` counts arcs.
    """
    for bend, marks in ((ROOMY, 2), (TIGHT, 0)):
        fs = _pair(bend)
        svg = _svg(fs)
        assert sum(_marks(svg)) == marks
        assert len(unmarked_crossings(fs)) == _crossings(fs) - marks
        assert len(_found(fs)) == _crossings(fs) - marks


def _crossings(fs) -> int:
    """Every point where a vertical run crosses a horizontal one, room or no
    room -- built from the model here and not from the renderer's own lists."""
    horizontal, vertical = [], []
    for s in fs.streams:
        points = stream_polyline(s)
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            if y1 == y2 and x1 != x2:
                horizontal.append((s, min(x1, x2), max(x1, x2), y1))
            elif x1 == x2 and y1 != y2:
                vertical.append((s, min(y1, y2), max(y1, y2), x1))
    return sum(
        1
        for run, lo, hi, at in vertical
        for other, c_lo, c_hi, c_at in horizontal
        if run is not other and c_lo < at < c_hi and lo < c_at < hi
    )


def test_a_crossing_moved_clear_stops_being_reported():
    """The finding is a fact about *this* render and is replaced by the next,
    like the fit findings beside it. A sheet redrawn with the crossing pinned
    clear that went on warning about it would send its author looking for a
    defect they had already fixed."""
    fs = _pair(TIGHT)
    _svg(fs)
    assert _found(fs)
    fs.streams[1].route = Route(
        waypoints=[(300.0, 375.0), (300.0, ROOMY), (400.0, ROOMY), (400.0, 375.0)]
    )
    _svg(fs)
    assert not _found(fs)


def test_the_corpus_leaves_no_crossing_bare():
    """All 50 crossings on the shipped sheets carry a mark, at either style.

    It was 49 of 50 while a material run was drawn at twice the equipment:
    ``HOP_R`` is the hop's clearance plus a pen, so the wider run needed more
    clear line either side of a crossing than 19_absorber_stripper had at one
    of its corners. At the restored rung the mark fits and the corpus is clean.

    This is the measurement that makes the cases above guards rather than
    descriptions of the corpus -- and with ``BARE`` empty it is the only thing
    holding the shipped sheets to a number, so it asserts zero outright rather
    than looping over a table that no longer has entries.
    """
    for stem in gallery.sheets():
        fs, kwargs = gallery.flowsheet(stem)
        # Rendered first: the crossings only exist once the sheet is laid
        # out and routed, and the finding is the render's own.
        fs.to_svg(**kwargs)
        assert len(_found(fs)) == BARE.get(stem, 0), stem
        direction = kwargs.get("jump_direction", "vertical")
        for style in ("arc", "gap"):
            assert len(unmarked_crossings(fs, direction, style)) == BARE.get(stem, 0), (stem, style)


def test_every_crossing_style_default_is_the_package_default():
    """One default, in eleven signatures.

    ``crossing_style`` is taken by four public entry points and by the
    helpers underneath them, and each states its own default because
    ``pandid.flowsheet`` imports ``pandid.render.svg`` lazily and cannot
    name the constant at ``def`` time. That is eleven copies of one
    value, which is exactly how a package ends up drawing one thing from
    the CLI and another from Python.

    So the copies are checked rather than trusted: every parameter named
    ``crossing_style`` anywhere in the package must default to
    :data:`~pandid.render.svg.CROSSING_STYLE_DEFAULT`, and the CLI's
    ``--crossing-style`` must too.
    """
    import inspect
    import pkgutil
    import importlib

    import pandid
    from pandid.render.svg import CROSSING_STYLE_DEFAULT, CROSSING_STYLES

    assert CROSSING_STYLE_DEFAULT in CROSSING_STYLES

    seen = 0
    for info in pkgutil.walk_packages(pandid.__path__, "pandid."):
        module = importlib.import_module(info.name)
        for _, obj in inspect.getmembers(module, inspect.isfunction):
            if obj.__module__ != info.name:
                continue
            parameter = inspect.signature(obj).parameters.get("crossing_style")
            if parameter is None or parameter.default is inspect.Parameter.empty:
                continue
            seen += 1
            assert parameter.default == CROSSING_STYLE_DEFAULT, (
                f"{info.name}.{obj.__qualname__} defaults crossing_style to "
                f"{parameter.default!r}, not {CROSSING_STYLE_DEFAULT!r}"
            )
    assert seen, "no crossing_style parameter was found, so nothing was checked"
