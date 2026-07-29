import html
import re

import pytest

from pandid import Flowsheet, units as U
from pandid.layout.attach import stream_path
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
_PROCESS_LINE = re.compile(r'<path d="([^"]+)" fill="none" stroke="[^"]*" stroke-width="2"')
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
    feed = fs.add(U.Feed("F")).pin(x=10, y=10)
    hx = fs.add(U.HeatExchanger("E-1")).pin(x=100, y=10)
    prod = fs.add(U.Product("P")).pin(x=200, y=10)

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
    fs.add(U.Feed("<Malicious>&")).pin(x=10, y=10)

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
