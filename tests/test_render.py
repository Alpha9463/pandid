import html
import re

import pytest

from pandid import Flowsheet, units as U
from pandid.layout.attach import stream_path
from pandid.render.svg import HOP_R, _ink, stream_polyline
from pandid.streams import SIGNAL_KINDS

from test_route_invariants import CORPUS

# A stream-number label: its opaque halo, then the text it backs.
_LABEL = re.compile(
    r'<rect x="([-\d.]+)" y="([-\d.]+)" width="([\d.]+)" height="([\d.]+)" fill="white" />\s*'
    r'(<text [^>]*font-size="10"[^>]*>)([^<]*)</text>'
)
# An equipment tag, the NC marking and the fail letters: the same halo, drawn at
# the size a symbol's own lettering is drawn at.
_TAG = re.compile(
    r'<rect x="([-\d.]+)" y="([-\d.]+)" width="([\d.]+)" height="([\d.]+)" fill="white" />\s*'
    r'<text [^>]*font-size="12"[^>]*>([^<]*)</text>'
)
#: A material run: ISO 10628-1 5.3.1 a), the ladder's main-flow rung. Written
#: out rather than interpolated, so moving a rung shows up here as a failure
#: rather than being absorbed by the regex that reads the sheet back.
_PROCESS_LINE = re.compile(r'<path d="([^"]+)" fill="none" stroke="[^"]*" stroke-width="4"')
_TAP_LINE = re.compile(
    r'<line x1="([-\d.]+)" y1="([-\d.]+)" x2="([-\d.]+)" y2="([-\d.]+)" stroke="black"'
)


def _stream_labels(svg):
    """``(halo box, text tag, name)`` for every stream number drawn on the sheet."""
    out = []
    for x, y, w, h, tag, name in _LABEL.findall(svg):
        x, y, w, h = float(x), float(y), float(w), float(h)
        out.append(((x, y, x + w, y + h), tag, name))
    return out


def _stream_runs(svg):
    """Straight runs of every drawn process line, as ``((x1, y1), (x2, y2))``."""
    runs = []
    for d in _PROCESS_LINE.findall(svg):
        pts = [tuple(map(float, p.split(","))) for p in re.findall(r"-?[\d.]+,-?[\d.]+", d)]
        runs += list(zip(pts, pts[1:]))
    return runs


def _covers(box, run):
    """Whether *box* swallows *run* end to end, leaving no line drawn."""
    x0, y0, x1, y1 = box
    return all(x0 <= x <= x1 and y0 <= y <= y1 for x, y in run)


def _overlaps(box, run):
    """Whether *box* touches any part of an axis-aligned *run*."""
    x0, y0, x1, y1 = box
    (rx0, ry0), (rx1, ry1) = run
    return (
        min(rx0, rx1) <= x1 and max(rx0, rx1) >= x0 and min(ry0, ry1) <= y1 and max(ry0, ry1) >= y0
    )


def test_render_svg_with_manual_placements(tmp_path):
    fs = Flowsheet("Render Test")
    feed = fs.add(U.Feed("F")).pin(x=60, y=35)
    hx = fs.add(U.HeatExchanger("E-1")).pin(x=100, y=10)
    prod = fs.add(U.Product("P")).pin(x=200, y=35)

    fs.connect(feed.outlet, hx.tube_in)
    fs.connect(hx.tube_out, prod.inlet).via([(150, 20), (150, 150)])

    out_path = tmp_path / "test.svg"
    fs.render(str(out_path))

    assert out_path.exists()
    content = out_path.read_text(encoding="utf-8")

    # Check root and defs
    assert "<svg" in content
    assert "<defs>" in content
    assert 'id="sym_hex"' in content

    # Check <use> tags for manually pinned coordinates
    assert "<polygon" in content
    assert 'fill="transparent"' in content
    # Pinned position is honored; dimensions come from the symbol.
    assert '<use href="#sym_hex" x="100" y="10"' in content

    # Stream paths carry their waypoints
    assert "150.0,20.0" in content
    assert "150.0,150.0" in content
    assert '<path d="' in content


def test_render_svg_escapes_xml(tmp_path):
    fs = Flowsheet("Render Test")
    fs.add(U.Feed("<Malicious>&")).pin(x=60, y=35)

    out_path = tmp_path / "test_escape.svg"
    fs.render(str(out_path))

    content = out_path.read_text(encoding="utf-8")
    assert "&lt;Malicious&gt;&amp;" in content
    assert "<Malicious>" not in content


def test_unit_labels_drawn_over_streams_with_a_halo():
    # Equipment tags are emitted after the stream group and backed by a white
    # halo, so a passing line can never strike through the text.
    fs = Flowsheet("Labels")
    feed = fs.add(U.Feed("F"))
    hx = fs.add(U.HeatExchanger("E-601"))
    prod = fs.add(U.Product("P"))
    fs.connect(feed.outlet, hx.tube_in)
    fs.connect(hx.tube_out, prod.inlet)
    svg = fs.to_svg()

    assert svg.index('id="unit_labels"') > svg.index('id="streams"')
    labels = svg[svg.index('id="unit_labels"') :]
    assert 'fill="white"' in labels  # halo behind the tag
    assert ">E-601<" in labels


def test_stream_number_labels_do_not_overprint():
    # Streams sharing a corridor sit a few px apart; their numbers must be slid
    # along the line rather than stacked on the same point.
    fs = Flowsheet("Crossing")
    f1, f2 = fs.add(U.Feed("Feed A")), fs.add(U.Feed("Feed B"))
    s1 = fs.add(U.Splitter("SP-501", n_outlets=2))
    s2 = fs.add(U.Splitter("SP-502", n_outlets=2))
    m1 = fs.add(U.Mixer("M-501", n_inlets=2))
    m2 = fs.add(U.Mixer("M-502", n_inlets=2))
    p1, p2 = fs.add(U.Product("Product A")), fs.add(U.Product("Product B"))
    fs.connect(f1.outlet, s1.inlet)
    fs.connect(f2.outlet, s2.inlet)
    fs.connect(s1.out_1, m1.in_1)
    fs.connect(s1.out_2, m2.in_1)
    fs.connect(s2.out_1, m1.in_2)
    fs.connect(s2.out_2, m2.in_2)
    fs.connect(m1.outlet, p1.inlet)
    fs.connect(m2.outlet, p2.inlet)
    svg = fs.to_svg()

    pts = [
        (float(x), float(y))
        for x, y in re.findall(r'<text x="([-\d.]+)" y="([-\d.]+)"[^>]*font-size="10"', svg)
    ]
    assert len(pts) >= 2
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            dx = abs(pts[i][0] - pts[j][0])
            dy = abs(pts[i][1] - pts[j][1])
            assert dx >= 12 or dy >= 12, f"labels overprint at {pts[i]} / {pts[j]}"


def _transfer_sheet():
    """Two short runs carrying line numbers far wider than the runs themselves."""
    fs = Flowsheet("Line Numbers")
    feed = fs.add(U.Feed("Raw Feed")).pin(x=60, y=100)
    valve = fs.add(U.Valve("FV-101", variant="control")).pin(x=180, y=110)
    prod = fs.add(U.Product("To Unit 200")).pin(x=280, y=100)
    valve.new_line_number = True  # a spec break, so each side is its own line
    fs.connect(feed.outlet, valve.inlet, size='8"', service="P", spec="A1A")
    fs.connect(valve.outlet, prod.inlet, size='6"', service="P", spec="D1B")
    return fs


def test_stream_label_halo_never_erases_its_own_run():
    # The halo is opaque and sized from the character count, so a line number is
    # wider than many of the runs it can land on. A halo that covers a run end to
    # end leaves a floating label with an arrowhead attached to nothing.
    svg = _transfer_sheet().to_svg()

    labels = _stream_labels(svg)
    assert len(labels) == 2
    for box, _, name in labels:
        for run in _stream_runs(svg):
            assert not _covers(box, run), f"{name} erases the run {run}"


def test_a_label_too_wide_for_its_run_is_written_beside_it():
    # No amount of sliding rescues a label wider than its run, so it steps off
    # the line entirely and leaves the pipe untouched.
    svg = _transfer_sheet().to_svg()

    runs = _stream_runs(svg)
    for box, _, name in _stream_labels(svg):
        assert not any(_overlaps(box, run) for run in runs), f"{name} still sits on a line"


def test_a_label_with_room_to_spare_stays_on_its_run():
    # The line number is the exception, not the rule: a stream number on an
    # ordinary run still reads as a break in the line, the way a sheet draws it.
    fs = Flowsheet("Plain")
    feed = fs.add(U.Feed("F")).pin(x=60, y=100)
    prod = fs.add(U.Product("P")).pin(x=400, y=100)
    fs.connect(feed.outlet, prod.inlet)
    svg = fs.to_svg()

    ((box, tag, _),) = _stream_labels(svg)
    assert any(_overlaps(box, run) for run in _stream_runs(svg))
    assert "rotate" not in tag  # a horizontal run needs no turning


def test_stream_label_on_a_vertical_run_reads_bottom_to_top():
    # A label follows its line, and a vertical one is turned so the sheet is
    # read from the right, never upside down. That is one of the two reading
    # directions ISO 15519-1 §5.1.5 allows, and §7.2.5 asks for a connection's
    # designation to be oriented along its line. Its halo turns with it, so the
    # box is taller than it is wide.
    fs = Flowsheet("Riser")
    feed = fs.add(U.Feed("F")).pin(x=60, y=300)
    prod = fs.add(U.Product("P")).pin(x=400, y=60)
    fs.connect(feed.outlet, prod.inlet).via([(250, 325), (250, 85)])
    svg = fs.to_svg()

    ((box, tag, _),) = _stream_labels(svg)
    assert 'transform="rotate(-90, ' in tag
    assert box[3] - box[1] > box[2] - box[0]


def test_render_svg_generic_symbol_duplicate_ids(tmp_path):
    fs = Flowsheet("Render Test Generic")

    class UnknownUnit1(U.Unit):
        kind = "unknown1"

    class UnknownUnit2(U.Unit):
        kind = "unknown2"

    fs.add(UnknownUnit1("U1")).pin(x=10, y=10)
    fs.add(UnknownUnit2("U2")).pin(x=200, y=20)

    out_path = tmp_path / "test_generic.svg"
    fs.render(str(out_path))

    content = out_path.read_text(encoding="utf-8")
    assert 'id="sym_unknown1"' in content
    assert 'id="sym_unknown2"' in content
    assert 'id="sym_generic"' not in content


# --- no halo deletes a line that is not its own, over the whole corpus ---------
# Every label on a sheet is written on an opaque rect and every one of them is
# drawn after the lines, so a halo in the wrong place does not sit *over* a line,
# it deletes a length of it and the drawing then says the run stops there. The
# topology is untouched by that, so ``validate()`` has nothing to report and the
# picture is the only witness -- which is why this is checked over every sheet
# the repo ships rather than on a specimen built to fail.
#
# The one line a halo may cover is the run whose number is written in it. A break
# in the line with the number in the break is the convention (ISO 15519-1
# §7.2.5), and the halo is what opens the break. Anything else -- a second line,
# a branch off its own line, the impulse line to a balloon -- is ink the label
# had no business erasing, and an equipment tag, which names a *symbol* and no
# run at all, may cover none of it.

# Half the weight of each line, being how far its ink reaches either side of the
# path it is drawn along. The renderer keeps a whole width clear (see
# ``pandid.render.svg._ink``); this asks only that no ink was actually deleted.
_INK_REACH = {"process": 1.0, "signal": 0.5}


def _tag_labels(svg):
    """``(halo box, text)`` for every equipment tag and marking on the sheet."""
    tags = svg[svg.index('id="unit_labels"') :]
    out = []
    for x, y, w, h, text in _TAG.findall(tags):
        x, y, w, h = float(x), float(y), float(w), float(h)
        out.append(((x, y, x + w, y + h), html.unescape(text)))
    return out


def _tap_runs(svg):
    """Every impulse line drawn, as ``((x1, y1), (x2, y2))``.

    Read back out of the SVG rather than recomputed from the model, so what is
    checked is the line the sheet actually carries.
    """
    if 'id="instrument_taps"' not in svg:
        return []
    taps = svg[svg.index('id="instrument_taps"') : svg.index('id="unit_labels"')]
    return [((float(a), float(b)), (float(c), float(d))) for a, b, c, d in _TAP_LINE.findall(taps)]


def _lines_drawn(fs, svg):
    """``(name, run, reach)`` for every line on the sheet.

    The streams come from :func:`~pandid.layout.attach.stream_path`, which is
    the polyline the renderer draws and so the only place a name is attached to
    a run; the impulse lines come from the SVG, and belong to no run.
    """
    out = []
    for s in fs.streams:
        reach = _INK_REACH["signal" if s.kind in SIGNAL_KINDS else "process"]
        points = stream_path(s)
        out += [(s.name, run, reach) for run in zip(points, points[1:])]
    out += [(None, run, _INK_REACH["signal"]) for run in _tap_runs(svg)]
    return out


def _deletes(box, run, reach):
    """Whether a halo at *box* would erase ink from *run*, drawn *reach* wide."""
    (rx0, ry0), (rx1, ry1) = run
    return (
        box[2] > min(rx0, rx1) - reach
        and box[0] < max(rx0, rx1) + reach
        and box[3] > min(ry0, ry1) - reach
        and box[1] < max(ry0, ry1) + reach
    )


def _is_own_run(box, upright, label, name, run):
    """Whether *run* is the very line this label's number is written in.

    Its own name, and lying along the halo's centreline: a label is turned to
    follow the run it names, so the run it is written *in* passes lengthwise
    through the middle of the halo. A branch off that same line crosses the halo
    instead of running through it, and is somebody else's ink even when the two
    share a line number, which on a P&ID a whole valve station does.
    """
    if name != label:
        return False
    (x1, y1), (x2, y2) = run
    if upright:
        return abs(x1 - x2) < 0.5 and abs((box[0] + box[2]) / 2 - x1) <= 1.0
    return abs(y1 - y2) < 0.5 and abs((box[1] + box[3]) / 2 - y1) <= 1.0


@pytest.fixture(scope="module")
def drawn():
    """Every shipped sheet, laid out, routed and rendered once, keyed by name."""
    sheets = {}
    for name, build in CORPUS.items():
        fs = build()
        fs.layout()
        fs.route()
        sheets[name] = (fs, fs.to_svg())
    return sheets


@pytest.mark.parametrize("name", list(CORPUS), ids=list(CORPUS))
def test_no_label_halo_deletes_a_line_that_is_not_its_own(drawn, name):
    fs, svg = drawn[name]
    lines = _lines_drawn(fs, svg)

    erased = []
    for box, tag, text in _stream_labels(svg):
        label = html.unescape(text)
        upright = "rotate(-90, " in tag  # a label on a riser is turned to follow it
        for owner, run, reach in lines:
            if _deletes(box, run, reach) and not _is_own_run(box, upright, label, owner, run):
                erased.append(f"{label!r} halo deletes {owner or 'an impulse line'} at {run}")
    for box, text in _tag_labels(svg):
        for owner, run, reach in lines:
            if _deletes(box, run, reach):
                erased.append(f"tag {text!r} halo deletes {owner or 'an impulse line'} at {run}")

    assert not erased, f"{name}: " + "; ".join(sorted(set(erased)))


@pytest.mark.parametrize("name", list(CORPUS), ids=list(CORPUS))
def test_a_hop_has_room_for_its_own_arc(drawn, name):
    """A hop is drawn on a crossing, never on the corner beside one.

    ``_draw_streams`` replaces a span of ``2 * HOP_R`` centred on the crossing
    with a semicircle. A crossing nearer than ``HOP_R`` to the end of the
    segment it sits on therefore has an arc that reaches past the end -- and
    where the run turns there, the bump is drawn on the elbow, which reads as a
    kink in the pipe rather than as one line passing over another.
    ``18_fixed_bed_recycle`` shipped one: a zero-length ``L`` at the corner
    followed immediately by the arc.

    Checked by counting, because the two halves are computed independently.
    Every arc in a stream's path is one hop, so the arcs in the drawing must
    number exactly the crossings that have the room -- which is the rule
    restated, and would fail if the renderer kept the old bound.
    """
    fs, svg = drawn[name]

    horizontals, verticals = [], []
    for s in fs.streams:
        pts = stream_polyline(s)
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            if y1 == y2 and x1 != x2:
                horizontals.append((min(x1, x2), max(x1, x2), y1))
            elif x1 == x2 and y1 != y2:
                verticals.append((x1, min(y1, y2), max(y1, y2)))

    expected = 0
    for s in fs.streams:
        pts = stream_polyline(s)
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            if x1 != x2:
                continue
            expected += sum(
                1
                for mnx, mxx, hy in horizontals
                if mnx < x1 < mxx and min(y1, y2) + HOP_R < hy < max(y1, y2) - HOP_R
            )

    drawn_arcs = sum(
        d.count(f"A {HOP_R:g} {HOP_R:g} ")
        for d in re.findall(r'<path d="(M [^"]*)"', svg)
        if " A " in d
    )
    assert drawn_arcs == expected, (
        f"{name}: {drawn_arcs} hop arcs drawn, {expected} crossings have room "
        f"for one -- a hop nearer than {HOP_R} to the end of its segment "
        f"overhangs, and on a corner is drawn as a kink"
    )


# ---------------------------------------------------------------------------
# A stream number is measured along its **own** run
# ---------------------------------------------------------------------------
#
# ``stream_numbers`` writes a number along the line it names and sends it
# away with a leader only where there is no room beside it, so how long
# the line *is* decides which of those two happens. A run is longer than
# the segment being labelled -- an in-line valve cuts a straight length
# of pipe into three drawn pieces and a reader sees one line -- so the
# length is gathered from every piece of ink collinear with it.
#
# Collinear is not the same as *the same run*. Two different streams
# drawn at one height are two lines, and a number that gathers both
# reads as written along one it has nothing to do with. ``_Ink.line``
# is what tells them apart; what follows is that it does.
#
# The consequence on a real drawing is measured in
# ``tests/test_label_invariants.py``, over the shipped corpus, which is
# where a leader drawn back across somebody else's run shows up. These
# two are about the seam itself.


def _collinear_pair():
    """Two unrelated runs drawn end to end at one height."""
    fs = Flowsheet("collinear")
    long_feed = fs.add(U.Feed("Long Feed")).pin(x=60, y=100)
    long_end = fs.add(U.Product("Long Product")).pin(x=700, y=100)
    short_feed = fs.add(U.Feed("Short Feed")).pin(x=820, y=100)
    short_end = fs.add(U.Product("Short Product")).pin(x=900, y=100)
    fs.connect(long_feed.outlet, long_end.inlet)
    fs.connect(short_feed.outlet, short_end.inlet)
    fs.layout()
    fs.route()
    return fs


def test_every_piece_of_pipe_ink_says_whose_run_it_is():
    """``_Ink.line`` is the stream's number, and a tap has none.

    A tap is the stub from a line to the balloon reading it and is not
    part of anybody's run, so it is left empty rather than given the
    instrument's name: an empty string matches no stream and so gathers
    into no run, which is the answer wanted.
    """
    fs = _collinear_pair()
    ink = _ink(fs)
    pipes = [piece for piece in ink if piece.kind == "pipe"]
    assert pipes, "the sheet drew no pipe"
    assert {piece.line for piece in pipes} == {s.name for s in fs.streams}
    assert all(piece.line == "" for piece in ink if piece.kind == "tap")


def test_two_runs_at_one_height_are_two_runs():
    """The short run's ink and the long one's do not pool.

    Both are horizontal and both are at ``y=100``, which is every test
    ``stream_numbers`` applied before ``line`` existed -- so measured
    that way the short run is 840 px long instead of 80 and has room to
    write anything anywhere. Measured by name the two do not touch.
    """
    fs = _collinear_pair()
    short = next(
        s for s in fs.streams if s.source.owner is not None and s.source.owner.name == "Short Feed"
    )
    level = [
        piece
        for piece in _ink(fs)
        if piece.kind == "pipe" and piece.axis == "h" and abs(piece.at - 100.0) < 0.5
    ]
    assert len({piece.line for piece in level}) == 2, (
        "the two runs are not collinear here, so this proves nothing"
    )
    mine = [piece for piece in level if piece.line == short.name]
    theirs = [piece for piece in level if piece.line != short.name]
    assert min(piece.x0 for piece in mine) > max(piece.x1 for piece in theirs), (
        "the short run's ink overlaps the long one's, so the two cannot be "
        "told apart by extent either"
    )
    assert max(piece.x1 for piece in mine) - min(piece.x0 for piece in mine) < 200, (
        "the short run measures longer than it is drawn"
    )


# --- a crossing the sheet could not mark --------------------------------------


def test_a_crossing_with_no_room_for_its_mark_is_reported():
    """The silent half of the hop, and #490 is what made it worth saying.

    ``_draw_streams`` marks a crossing with an arc, and only where the run
    carrying it has ``HOP_R`` of itself either side to sit on. Where it has
    less the arc is dropped and the two runs are laid straight through each
    other -- and on a sheet where every *other* crossing carries an arc, a bare
    one does not read as "no information", it reads as a junction. That was
    drawn and not said; it is said now.

    Held against the shipped corpus rather than a fixture, because the
    condition needs a crossing within a few units of a corner and the routes
    that produce one are exactly what a hand-built sheet cannot be trusted to
    reproduce.
    """
    from pandid.render.svg import unmarked_crossings

    from test_golden import SCENARIOS

    build, kwargs = SCENARIOS["18_fixed_bed_recycle"]
    fs = build()
    fs.to_svg(**kwargs)

    said = [w for w in fs.warnings if w.code == "crossing-unmarked"]
    assert len(said) == len(unmarked_crossings(fs)) == 1
    assert "350-LG-310-CS crosses 350-LG-314-CS at (1278, 629)" in said[0].message
    # The measurement a reader can check, and what to do about it.
    assert f"under {HOP_R:g}px of itself either side" in said[0].message
    assert "via()" in said[0].message


def test_a_sheet_whose_crossings_all_have_room_says_nothing():
    """The other side of it: the finding is about the crossings that lost their
    mark, not about having crossings at all."""
    from pandid.render.svg import unmarked_crossings

    from test_golden import SCENARIOS

    build, kwargs = SCENARIOS["21_alumina_refinery"]
    fs = build()
    fs.to_svg(**kwargs)
    assert unmarked_crossings(fs) == []
    assert [w for w in fs.warnings if w.code == "crossing-unmarked"] == []


def test_a_redrawn_sheet_drops_the_crossing_it_used_to_report():
    """A render's own findings describe *that* render, the rule ``_FIT_CODES``
    already follows: a sheet redrawn with the crossing moved clear must stop
    warning about it, rather than accumulating both answers."""
    from test_golden import SCENARIOS

    build, kwargs = SCENARIOS["18_fixed_bed_recycle"]
    fs = build()
    fs.to_svg(**kwargs)
    assert [w for w in fs.warnings if w.code == "crossing-unmarked"]
    # The same sheet drawn with the crossings marked the other way round: the
    # horizontal carries the arc, and it has the room the vertical lacked.
    fs.to_svg(**{**kwargs, "jump_direction": "horizontal"})
    assert [w for w in fs.warnings if w.code == "crossing-unmarked"] == []
