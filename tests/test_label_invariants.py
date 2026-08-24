"""What a line number on a drawn sheet has to be, over the whole shipped corpus.

**A line number is written along the line it names, or carries a leader to it.**

That is BS ISO 15519-1:2010 §7.2.5, on the reference designation of a
connection, and both halves of it are *shall*: the designation is oriented along
or beside the connecting line it belongs to, and where there is no room beside
that line it goes elsewhere in the content area with a leader drawn back to it
(the clause points on to 6.4).

Nothing asserted it. The placement search walked outward from the pipe until it
found paper nothing else had claimed and wrote the number there, however far out
that turned out to be, with nothing joining it to its line -- and on
``11_ethanol_pid`` three numbers ended up 30 units of blank paper from their own
run, close against a vessel, a valve tag and a reboiler shell respectively
(issue #155 item 4). The avoidance was working; the outcome defeated its
purpose, and every test passed.

*Along* is measured as overlap and not as a gap, which is the second thing this
file has been wrong about. The first version of these checks read "adjacent" as
a distance across the paper and asserted a cap on it, and that cap was
answering a question no reader asks. ``FB-306-100-160-SS`` on 11 stands two
bands off its own run and is not in the least ambiguous, because the run goes
the whole length of the number and out past both ends; it was given a leader for
being far away, and the leader is what put a second reading on the sheet, since
it lands under one half of a number that was already sitting over its line.
What decides it is whether the line is *there*, beside the words: a caption is
attached by lying against the thing it captions, and a string that has run out
past the end of its own line is lying against something else instead.

The checks read the drawn SVG rather than the placement code, because what the
clause is about is what a reader sees. Each label's halo, its text and the
leader that may follow are picked out of the ``streams`` group in document
order, and measured against the polyline its own line is drawn as.

The run measured against is the whole straight length of the labelled line the
label lies along, not one drawn segment of it: an in-line valve splits a
straight run of pipe into three pieces and a reader sees one line. It has to be
parallel to the label, too, since a number written along a horizontal run is not
made to lie along anything by a vertical stub of the same line passing near its
end.

§6.4 governs the leader itself, and its three checks are here too: the leader
lands *on* the line it names, it is oblique, and it cuts nothing. Oblique
matters because §12.1 holds every connecting line -- pipes, mechanical links,
conductors, functional connections -- to horizontal or vertical, so the
slope is what stops a leader being read as a connection; ISO 15519-1's own
Figure 4 c), the case of a leader landing on a plain connection, draws it that
way. And cutting nothing matters because the label was moved out here to avoid
deleting somebody else's ink in the first place: a leader that runs through what
the halo stepped around has moved the defect rather than fixed it.
"""

import html
import importlib.util
import math
import re
import sys
from pathlib import Path

import pytest

from pandid import Flowsheet, units as U
from pandid.layout.attach import stream_path
from pandid.portgeom import unit_box
from pandid.render.svg import _along, _crosses, _ink, _SIGNAL_KINDS

from test_golden import SCENARIOS

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
TOL = 0.01

_RECT = re.compile(
    r'<rect x="([-\d.]+)" y="([-\d.]+)" width="([\d.]+)" '
    r'height="([\d.]+)" fill="white" />'
)
_TEXT = re.compile(
    r'<text x="[-\d.]+" y="[-\d.]+"[^>]*?(transform="rotate[^"]*")?>'
    r"([^<]*)</text>"
)
_LEAD = re.compile(
    r'<line x1="([-\d.]+)" y1="([-\d.]+)" x2="([-\d.]+)" y2="([-\d.]+)" '
    r'stroke="[^"]*" stroke-width="1" />'
)
_HEAD = re.compile(
    r'<path d="M [-\d.]+,[-\d.]+ L [-\d.]+,[-\d.]+ '
    r'L [-\d.]+,[-\d.]+ Z" fill="[^"]*" />'
)


# --- the corpus ---------------------------------------------------------------


def _example(stem: str) -> "tuple[Flowsheet, dict]":
    """An example's flowsheet and the options it renders itself with.

    The keywords matter as much as the topology: 11 is the P&ID, and a P&ID
    draws no flow arrowheads, so rendering it as anything else would be
    measuring a sheet nobody ships.
    """
    sys.path.insert(0, str(EXAMPLES))  # the examples' own _bootstrap
    try:
        spec = importlib.util.spec_from_file_location(f"_labels_{stem}", EXAMPLES / f"{stem}.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(EXAMPLES))

    built: list = []
    original = Flowsheet.render

    def capture(self, _path=None, **kwargs):
        built.append((self, kwargs))

    Flowsheet.render = capture  # type: ignore[method-assign]
    try:
        module.main()
    finally:
        Flowsheet.render = original  # type: ignore[method-assign]
    return built[0]


def _crowded_number() -> "tuple[Flowsheet, dict]":
    """A sheet built so one line number cannot be written beside its own run.

    The corpus is the real evidence, but it is also free to change: a sheet is
    edited, a number finds room beside its line, and the leader checks below go
    quiet while still passing. This one is arranged so that cannot happen, and
    arranged on the thing that decides it rather than on the crowding around it.
    The drum sits 25 units under a short vertical drop carrying a fifteen-
    character line number, so the number is three times the length of the run it
    names: wherever it is written, two thirds of it has no line beside it, and no
    amount of clear paper anywhere on the sheet can change that.
    """
    fs = Flowsheet("crowded", line_numbering_scheme="{service}-{sequence}-{size}-{spec}")
    feed = fs.add(U.Feed("F"))
    top = fs.add(U.HeatExchanger("E-1", variant="straight_tubes", width=130, height=40))
    drum = fs.add(U.Vessel("V-1", variant="horizontal", width=130, height=42))
    prod = fs.add(U.Product("P"))
    top.pin(x=300, y=100)
    drum.nozzle("inlet", "N")
    drum.pin(x=300, y=165)
    feed.pin(port="outlet", x=100, y=120)
    prod.pin(port="inlet", x=600, y=186)
    fs.connect(feed.outlet, top.shell_in, service="AE", sequence=304, size=150, spec="SS")
    fs.connect(top.shell_out, drum.inlet, service="AE", sequence=305, size=150, spec="SS")
    fs.connect(drum.outlet, prod.inlet, service="AE", sequence=306, size=100, spec="SS")
    return fs, {}


CORPUS: dict = {name: (lambda b=build, k=kw: (b(), k)) for name, (build, kw) in SCENARIOS.items()}
CORPUS["10_ethanol_pfd"] = lambda: _example("10_ethanol_pfd")
CORPUS["11_ethanol_pid"] = lambda: _example("11_ethanol_pid")
CORPUS["crowded_number"] = _crowded_number

#: The options a corpus sheet is redrawn with here, which have to be the options
#: it ships with or these checks are run on a picture nobody sees.
#: ``connections`` was missing and the omission was invisible: the flange marks
#: are ink the number search dodges and the leader clearance counts, and 11 is
#: the only flanged sheet in the corpus, so dropping it ran every check in this
#: file and in ``test_halo_invariants`` against the one sheet that carries them
#: with them turned off.
_RENDER_OPTS = (
    "page_size",
    "border",
    "diagram",
    "jump_direction",
    "show_stream_table",
    "connections",
)


# --- reading the drawn sheet --------------------------------------------------


class Label:
    """One drawn line number: its halo, its text, and its leader if it has one."""

    def __init__(self, box, name, turned, leader, head):
        self.box, self.name, self.turned = box, name, turned
        self.leader, self.head = leader, head


def _labels(svg: str) -> "list[Label]":
    """Every stream label on a rendered sheet, in the order it was drawn.

    The label pass is the tail of the ``streams`` group and is the only thing in
    it that emits a white ``<rect>``, so splitting on those gives one chunk per
    label, each holding that label's text and any leader drawn for it.
    """
    group = svg.split('<g id="streams">', 1)[1].split("\n  </g>", 1)[0]
    out = []
    for chunk in group.split("<rect x=")[1:]:
        chunk = "<rect x=" + chunk
        rect = _RECT.search(chunk)
        text = _TEXT.search(chunk)
        assert rect and text, chunk[:200]
        x, y, w, h = (float(rect.group(i)) for i in (1, 2, 3, 4))
        lead = _LEAD.search(chunk)
        out.append(
            Label(
                box=(x, y, x + w, y + h),
                name=html.unescape(text.group(2)),
                turned=bool(text.group(1)),
                leader=(
                    (
                        (float(lead.group(1)), float(lead.group(2))),
                        (float(lead.group(3)), float(lead.group(4))),
                    )
                )
                if lead
                else None,
                head=bool(_HEAD.search(chunk)),
            )
        )
    return out


def _drawn_segments(fs) -> dict:
    """Every process line's drawn polyline, as segments keyed by line number."""
    segs: dict = {}
    for s in fs.streams:
        if s.kind in _SIGNAL_KINDS or not s.name:
            continue
        points = stream_path(s)
        segs.setdefault(s.name, []).extend(zip(points, points[1:]))
    return segs


def _gap(box, seg) -> float:
    """Clear distance from a rectangle to an axis-aligned segment."""
    (ax, ay), (bx, by) = seg
    r = (min(ax, bx), min(ay, by), max(ax, bx), max(ay, by))
    dx = max(r[0] - box[2], box[0] - r[2], 0.0)
    dy = max(r[1] - box[3], box[1] - r[3], 0.0)
    return math.hypot(dx, dy)


def _parallel(segs, turned):
    """The segments of a line that a label lying along it could be lying along.

    A label is turned to follow its run, so a turned one names a vertical
    segment and an upright one a horizontal segment. Zero-length hops between
    coincident points are dropped: they are drawn as nothing and so name
    nothing.
    """
    out = []
    for (ax, ay), (bx, by) in segs:
        vertical = abs(bx - ax) < TOL
        if abs(bx - ax) < TOL and abs(by - ay) < TOL:
            continue
        if vertical == turned:
            out.append(((ax, ay), (bx, by)))
    return out


def _runs(segs, turned):
    """The straight lengths of line a label could be written along, as spans.

    Segments parallel to the label are grouped by the infinite line they lie on
    and their extents merged, so a run broken into three pieces by an in-line
    valve is one run again -- which is what it looks like on paper. Returned in
    the label's own coordinate: ``y`` where the label is turned, ``x`` where it
    is not.
    """
    lines: dict = {}
    for (ax, ay), (bx, by) in _parallel(segs, turned):
        at = round(ax if turned else ay, 1)
        lo, hi = (min(ay, by), max(ay, by)) if turned else (min(ax, bx), max(ax, bx))
        got = lines.get(at)
        lines[at] = (min(lo, got[0]), max(hi, got[1])) if got else (lo, hi)
    return list(lines.values())


def _alongness(box, turned, runs) -> float:
    """The longest fraction of a label that has one of *runs* beside it."""
    a, b = (box[1], box[3]) if turned else (box[0], box[2])
    return max((min(b, hi) - max(a, lo) for lo, hi in runs), default=0.0) / (b - a)


@pytest.fixture(scope="module")
def sheets():
    """Every sheet in the corpus, rendered once, as (flowsheet, labels)."""
    out = {}
    for name, build in CORPUS.items():
        fs, kwargs = build()
        svg = fs.to_svg(**{k: v for k, v in kwargs.items() if k in _RENDER_OPTS})
        out[name] = (fs, _labels(svg))
    return out


# --- §7.2.5: along, or led ---------------------------------------------------


@pytest.mark.parametrize("name", list(CORPUS), ids=list(CORPUS))
def test_a_line_number_is_written_along_its_line_or_carries_a_leader(sheets, name):
    fs, labels = sheets[name]
    segs = _drawn_segments(fs)
    adrift = []
    for label in labels:
        runs = _runs(segs.get(label.name, []), label.turned)
        assert runs, f"{name}: {label.name} lies along no run of its own line"
        share = _alongness(label.box, label.turned, runs)
        if share <= 0.5 and label.leader is None:
            adrift.append(f"{label.name} has its own line beside {share:.0%} of it and no leader")
    assert not adrift, f"{name}: " + "; ".join(adrift)


@pytest.mark.parametrize("name", list(CORPUS), ids=list(CORPUS))
def test_a_leader_lands_on_the_line_it_names(sheets, name):
    """§6.4: a leader ending on the outline of an object, or on a connection,
    terminates in an arrowhead. A leader that stops short of its connection
    points at whatever it stopped over instead."""
    fs, labels = sheets[name]
    segs = _drawn_segments(fs)
    wrong = []
    for label in labels:
        if label.leader is None:
            continue
        end = label.leader[1]
        landed = min(_gap((end[0], end[1], end[0], end[1]), seg) for seg in segs[label.name])
        if landed > TOL:
            wrong.append(f"{label.name}'s leader stops {landed:.1f} short of its line")
        if not label.head:
            wrong.append(f"{label.name}'s leader carries no arrowhead")
    assert not wrong, f"{name}: " + "; ".join(wrong)


@pytest.mark.parametrize("name", list(CORPUS), ids=list(CORPUS))
def test_a_leader_is_oblique(sheets, name):
    """So it cannot be read as a connection. §12.1 orients every connecting line
    horizontally or vertically, which is what tests/test_route_invariants.py
    enforces on the streams and the impulse lines; the slope is the whole of
    what tells a reader this line is neither."""
    flat = []
    for label in sheets[name][1]:
        if label.leader is None:
            continue
        (x0, y0), (x1, y1) = label.leader
        if abs(x1 - x0) < TOL or abs(y1 - y0) < TOL:
            flat.append(f"{label.name}'s leader runs ({x0:.0f}, {y0:.0f}) -> ({x1:.0f}, {y1:.0f})")
    assert not flat, f"{name}: " + "; ".join(flat)


@pytest.mark.parametrize("name", list(CORPUS), ids=list(CORPUS))
def test_a_leader_cuts_nothing_the_label_was_dodging(sheets, name):
    """A leader is new ink on a sheet already too crowded to write the number
    beside its line. Running it through the vessel the halo stepped around, or
    through a line that is not the one it names, moves the defect instead of
    fixing it -- and unlike the halo it does not even delete the ink honestly,
    it simply crosses it."""
    fs, labels = sheets[name]
    boxes = [unit_box(u, u.frame) for u in fs.units if u.frame is not None]
    ink = _ink(fs)
    segs = _drawn_segments(fs)
    cutting = []
    for label in labels:
        if label.leader is None:
            continue
        # A leader ends *on* its own line, so that line's own ink is not
        # something it cuts through. Named the way the placement search names
        # it: by the infinite line a segment lies on.
        own = {
            (
                ("v" if abs(b[0] - a[0]) < TOL else "h"),
                round(a[0] if abs(b[0] - a[0]) < TOL else a[1], 1),
            )
            for a, b in segs[label.name]
        }
        for box in boxes:
            if _crosses(*label.leader, box):
                cutting.append(
                    f"{label.name}'s leader crosses a unit at ({box[0]:.0f}, {box[1]:.0f})"
                )
        for line in ink:
            if (line.axis, round(line.at, 1)) in own:
                continue
            if _crosses(*label.leader, line.box):
                cutting.append(
                    f"{label.name}'s leader crosses a {line.kind} at {line.axis}={line.at:.0f}"
                )
    assert not cutting, f"{name}: " + "; ".join(cutting)


# --- guarding the guards ------------------------------------------------------


def test_the_corpus_still_draws_a_leader(sheets):
    """Three of the checks above are vacuous on a sheet with no leader on it, so
    say outright that the corpus still contains one. ``crowded_number`` is built
    to keep that true whatever happens to the shipped sheets."""
    drawn = {name: sum(1 for lab in labels if lab.leader) for name, (_fs, labels) in sheets.items()}
    assert drawn["crowded_number"] >= 1, drawn
    assert sum(drawn.values()) >= 2, drawn


def test_along_is_more_than_half_the_words_and_nothing_about_the_gap():
    """Where the line falls, stated on the function itself rather than inferred
    from a sheet. It is a judgement about what reads and it should not move
    silently; and the second half of it -- that the stand-off across the paper
    is not part of the question -- is the whole of what changed."""
    box = (0.0, 100.0, 100.0, 113.0)  # a hundred units of upright label
    assert _along(box, False, 0.0, 51.0)
    assert not _along(box, False, 0.0, 50.0)
    assert not _along(box, False, 60.0, 400.0)  # 40 alongside, out of 100
    assert _along(box, False, -400.0, 400.0)  # a run running past both ends

    # The same label a whole sheet away from its run, and still along it.
    assert _along((0.0, 900.0, 100.0, 913.0), False, -400.0, 400.0)

    # Turned, the length that has to be covered is the halo's height.
    assert _along((100.0, 0.0, 113.0, 100.0), True, 0.0, 51.0)
    assert not _along((100.0, 0.0, 113.0, 100.0), True, 0.0, 50.0)


def test_a_leader_is_drawn_only_where_the_line_is_not_beside_the_words(sheets):
    """The other half of the rule, which the check above cannot state: a number
    with its own run beside most of it does not get a leader *as well*.

    Both directions matter, and the corpus is the evidence for the line falling
    where it does. Of 286 numbers on the 21 shipped sheets 25 have their own
    run beside less than the whole of them, and they part into two groups
    with a gap between: 21 read as their own line's unaided, from
    ``MS-605-200-40-CS`` on 14 at 60 % to ``E10-609-200-40-CS`` on 14 at 98 %,
    and four do not -- ``100-CWS-209-CS`` on 17 at 18 %, ``AE-304-150-80-SS``
    on 11 at 29 %, ``MS-601-200-40-CS`` on 14 at 34 % and ``S-403`` on 13 at
    36 %, the second of those the last sixteen characters naming a
    thirty-unit stub with two thirds of it lying against a reflux drum.

    The gap is 36 % to 60 %, narrower than the 40 % to 61 % the fourteen-sheet
    corpus showed and the 32 % to 74 % the twelve-sheet corpus showed before
    that; see :func:`pandid.render.svg._along` for what that is and is not
    evidence for. This test is one of the two that would fail first if a
    number ever landed inside it.
    """
    over, under = [], []
    for name, (fs, labels) in sheets.items():
        segs = _drawn_segments(fs)
        for label in labels:
            runs = _runs(segs.get(label.name, []), label.turned)
            share = _alongness(label.box, label.turned, runs)
            if share > 0.5 and label.leader is not None:
                over.append(f"{name}/{label.name} at {share:.0%}")
            if share <= 0.5 and label.leader is None:
                under.append(f"{name}/{label.name} at {share:.0%}")
    assert not over, "led although written along its line: " + "; ".join(over)
    assert not under, "not written along its line and not led: " + "; ".join(under)


def test_the_p_and_id_needs_exactly_one_leader(sheets):
    """The sheet the defect was reported on. Named here so a change that quietly
    stops drawing them, or starts drawing a dozen, is a red suite rather than a
    silent regression in the drawing.

    One, and not the three it used to draw. ``FB-301`` and ``FB-306`` both sit
    over the run they name, along its whole length; leading them said there was
    a question about which line they belonged to when there was not, and pointed
    the answer at one end of a number that spans the run.
    """
    _fs, labels = sheets["11_ethanol_pid"]
    led = sorted(lab.name for lab in labels if lab.leader)
    assert led == ["AE-304-150-80-SS"]


def test_a_leader_leaves_the_lettering_and_not_the_paper_beside_it(sheets):
    """A halo is measured at 6,2 per character plus padding, so its corners are
    blank paper -- more of it the more hyphens the number has, and a line number
    is mostly hyphens. A tail on a corner starts past the end of the last letter
    with a gap between the two, and a mark that does not touch the words does
    not attach them to anything. ``AE-304-150-80-SS`` was led from the top
    corner of a rotated halo for exactly that reason.

    Half the halo's thickness in from each end is what :func:`_leader` insets
    by; asserted here as a fraction of the halo so it is a statement about the
    drawing rather than a copy of the constant.
    """
    off_the_words = []
    for name, (_fs, labels) in sheets.items():
        for label in labels:
            if label.leader is None:
                continue
            (x0, y0), _end = label.leader
            box = label.box
            # The tail sits on the face nearest the run and somewhere along the
            # other axis; that along-axis coordinate is the one that has to be
            # on the lettering rather than on the halo's padding.
            at, lo, hi = (y0, box[1], box[3]) if label.turned else (x0, box[0], box[2])
            keep = min(13.0 / 2, (hi - lo) / 4)
            if not (lo + keep - TOL <= at <= hi - keep + TOL):
                off_the_words.append(
                    f"{name}/{label.name} leaves at {at:.1f} of {lo:.1f}..{hi:.1f}"
                )
    assert not off_the_words, "; ".join(off_the_words)
