"""What a line number on a drawn sheet has to be, over the whole shipped corpus.

**A line number is adjacent to the line it names, or carries a leader to it.**

That is BS ISO 15519-1:2010 §7.2.5, on the reference designation of a
connection, and both halves of it are *shall*: "They shall be oriented along or
adjacent to the relevant connecting lines. If it is not possible to place the
reference designation adjacent to the connecting line, it shall be shown
elsewhere in the content area with a leader line to the actual connecting line.
See also 6.4."

Nothing asserted it. The placement search walked outward from the pipe until it
found paper nothing else had claimed and wrote the number there, however far out
that turned out to be, with nothing joining it to its line -- and on
``11_ethanol_pid`` three numbers ended up 30 units of blank paper from their own
run, close against a vessel, a valve tag and a reboiler shell respectively, each
reading as an annotation of the thing it was nearest (issue #155 item 4). The
avoidance was working; the outcome defeated its purpose, and every test passed.

The checks read the drawn SVG rather than the placement code, because what the
clause is about is what a reader sees. Each label's halo, its text and the
leader that may follow are picked out of the ``streams`` group in document
order, and measured against the polyline its own line is drawn as.

Adjacency is measured to the nearest **parallel** segment of the labelled line,
which is the one the label lies along: a number written across a line's
horizontal run is not made adjacent by a vertical stub of the same line passing
somewhere near its end.

§6.4 governs the leader itself, and its three checks are here too: the leader
lands *on* the line it names, it is oblique, and it cuts nothing. Oblique
matters because §12.1 holds every connecting line -- "pipelines, mechanical
links, conductors, functional connections" -- to horizontal or vertical, so the
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
from pandid.render.svg import _crosses, _ink, _label_reach, _LABEL_GAP, _SIGNAL_KINDS

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
    quiet while still passing. This one is arranged so that cannot happen. The
    drum is 25 units under a short vertical drop carrying a fifteen-character
    line number, so the number is three times the length of the run it names and
    every band beside that run is either the drum or the exchanger above it.
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

_RENDER_OPTS = ("page_size", "border", "diagram", "jump_direction", "show_stream_table")


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


@pytest.fixture(scope="module")
def sheets():
    """Every sheet in the corpus, rendered once, as (flowsheet, labels)."""
    out = {}
    for name, build in CORPUS.items():
        fs, kwargs = build()
        svg = fs.to_svg(**{k: v for k, v in kwargs.items() if k in _RENDER_OPTS})
        out[name] = (fs, _labels(svg))
    return out


# --- §7.2.5: adjacent, or led ------------------------------------------------


@pytest.mark.parametrize("name", list(CORPUS), ids=list(CORPUS))
def test_a_line_number_is_adjacent_to_its_line_or_carries_a_leader(sheets, name):
    fs, labels = sheets[name]
    segs = _drawn_segments(fs)
    # The stand-off a label may be written at without a leader, measured as the
    # clear paper between its halo and the line: _label_reach is to the halo's
    # centre, and half the halo is not blank paper.
    reach = _label_reach(13.0) - 13.0 / 2
    adrift = []
    for label in labels:
        mine = _parallel(segs.get(label.name, []), label.turned)
        assert mine, f"{name}: {label.name} lies along no segment of its own line"
        gap = min(_gap(label.box, seg) for seg in mine)
        if gap > reach + TOL and label.leader is None:
            adrift.append(f"{label.name} is {gap:.1f} from its line with no leader")
    assert not adrift, f"{name}: " + "; ".join(adrift)


@pytest.mark.parametrize("name", list(CORPUS), ids=list(CORPUS))
def test_a_leader_lands_on_the_line_it_names(sheets, name):
    """§6.4: the leader "shall terminate ... with an arrowhead if it ends on the
    outline of an object or a connection". A leader that stops short of its
    connection points at whatever it stopped over instead."""
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


def test_the_cap_is_the_stand_off_one_band_out(sheets):
    """The cap is derived, not chosen, and this is where the derivation is
    pinned: one label height of blank paper beyond the gap a label beside its
    run is written at. Change it and this fails, which is the point -- it is a
    judgement about what reads, and it should not move silently."""
    assert _label_reach(13.0) == 13.0 / 2 + _LABEL_GAP + 13.0
    assert _label_reach(13.0) - 13.0 / 2 == _LABEL_GAP + 13.0


def test_the_p_and_id_still_needs_three_leaders(sheets):
    """The sheet the defect was reported on. Named here so a change that quietly
    stops drawing them, or starts drawing a dozen, is a red suite rather than a
    silent regression in the drawing."""
    _fs, labels = sheets["11_ethanol_pid"]
    led = sorted(lab.name for lab in labels if lab.leader)
    assert led == ["AE-304-150-80-SS", "FB-301-200-160-SS", "FB-306-100-160-SS"]
