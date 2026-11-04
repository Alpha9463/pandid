"""Check that each line number is written along its line or carries a leader to it
(ISO 15519-1 §7.2.5, §6.4), over every corpus sheet.
"""

import html
import math
import re

import pytest

from pandid import Flowsheet, units as U
from pandid.layout.attach import stream_path
from pandid.portgeom import unit_box
from pandid.render.svg import _along, _crosses, _ink, _SIGNAL_KINDS, UPRIGHT_ENCLOSURES

from test_golden import SCENARIOS

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


def _crowded_number() -> "tuple[Flowsheet, dict]":
    """Build a sheet where one line number cannot be written beside its run."""
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


def _short_run() -> "tuple[Flowsheet, dict]":
    """Build a sheet whose one line is under half as long as its number."""
    fs = Flowsheet("short run")
    feed = fs.add(U.Feed("F"))
    prod = fs.add(U.Product("P"))
    feed.pin(port="outlet", x=100, y=100)
    prod.pin(port="inlet", x=114, y=100)
    fs.connect(feed.outlet, prod.inlet, service="P", sequence=1, spec="A")
    return fs, {}


CORPUS: dict = {name: (lambda b=build, k=kw: (b(), k)) for name, (build, kw) in SCENARIOS.items()}
CORPUS["crowded_number"] = _crowded_number
CORPUS["short_run"] = _short_run

#: The render options a corpus sheet ships with, which these checks redraw it with.
_RENDER_OPTS = (
    "page_size",
    "border",
    "diagram",
    "jump_direction",
    "show_stream_table",
    "connections",
)


def _codes_beside_a_flange() -> "tuple[Flowsheet, dict]":
    """Build a flanged sheet whose alarm codes would fall on a valve's flange."""
    fs = Flowsheet("codes beside a flange")
    feed = fs.add(U.Feed("F"))
    valve = fs.add(U.Valve("HV-1"))
    prod = fs.add(U.Product("P"))
    feed.pin(port="outlet", x=100, y=200)
    valve.pin(port="inlet", x=180, y=140)
    prod.pin(port="inlet", x=380, y=140)
    riser = fs.connect(feed.outlet, valve.inlet)
    fs.connect(valve.outlet, prod.inlet)
    fs.add_instrument("PI", 1, sensing=riser, at=0.6).annotate(high="PAH", low="PAL")
    return fs, {"diagram": "p&id", "connections": "flanged"}


CORPUS["codes_beside_a_flange"] = _codes_beside_a_flange


# --- reading the drawn sheet --------------------------------------------------


class Label:
    """One drawn line number: its halo, its text, and its leader if it has one."""

    def __init__(self, box, name, turned, leader, head):
        self.box, self.name, self.turned = box, name, turned
        self.leader, self.head = leader, head


def _labels(svg: str) -> "list[Label]":
    """Return every stream label on a rendered sheet, in the order it was drawn."""
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
    """Return every process line's drawn polyline, as segments keyed by line number."""
    segs: dict = {}
    for s in fs.streams:
        if s.kind in _SIGNAL_KINDS or not s.name:
            continue
        points = stream_path(s)
        segs.setdefault(s.name, []).extend(zip(points, points[1:]))
    return segs


def _gap(box, seg) -> float:
    """Return clear distance from a rectangle to an axis-aligned segment."""
    (ax, ay), (bx, by) = seg
    r = (min(ax, bx), min(ay, by), max(ax, bx), max(ay, by))
    dx = max(r[0] - box[2], box[0] - r[2], 0.0)
    dy = max(r[1] - box[3], box[1] - r[3], 0.0)
    return math.hypot(dx, dy)


def _line_axis(segs, box) -> bool:
    """Return which way the piece of line this label is written on runs."""
    centre = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
    point = (centre[0], centre[1], centre[0], centre[1])
    nearest, vertical = None, False
    for (ax, ay), (bx, by) in segs:
        if abs(bx - ax) < TOL and abs(by - ay) < TOL:
            continue
        away = _gap(point, ((ax, ay), (bx, by)))
        if nearest is None or away < nearest:
            nearest, vertical = away, abs(bx - ax) < TOL
    return vertical


def _axis(label, segs, upright: bool) -> bool:
    """Return the axis to measure this label's alongness on."""
    if not upright:
        return label.turned
    return _line_axis(segs, label.box)


def _parallel(segs, along_vertical):
    """Return the segments of a line that a label lying along it could be lying along."""
    turned = along_vertical
    out = []
    for (ax, ay), (bx, by) in segs:
        vertical = abs(bx - ax) < TOL
        if abs(bx - ax) < TOL and abs(by - ay) < TOL:
            continue
        if vertical == turned:
            out.append(((ax, ay), (bx, by)))
    return out


def _runs(segs, turned):
    """Return the straight lengths of line a label could be written along, as spans."""
    lines: dict = {}
    for (ax, ay), (bx, by) in _parallel(segs, turned):
        at = round(ax if turned else ay, 1)
        lo, hi = (min(ay, by), max(ay, by)) if turned else (min(ax, bx), max(ax, bx))
        got = lines.get(at)
        lines[at] = (min(lo, got[0]), max(hi, got[1])) if got else (lo, hi)
    return list(lines.values())


def _alongness(box, turned, runs) -> float:
    """Return the longest fraction of a label that has one of *runs* beside it."""
    a, b = (box[1], box[3]) if turned else (box[0], box[2])
    return max((min(b, hi) - max(a, lo) for lo, hi in runs), default=0.0) / (b - a)


@pytest.fixture(scope="module")
def sheets(corpus_svg):
    """Parse the line numbers of every corpus sheet once."""
    return {name: (fs, _labels(svg)) for name, (fs, _options, svg) in corpus_svg.items()}


# --- §7.2.5: along, or led ---------------------------------------------------


@pytest.mark.parametrize("name", list(CORPUS), ids=list(CORPUS))
def test_a_line_number_is_written_along_its_line_or_carries_a_leader(sheets, name):
    fs, labels = sheets[name]
    segs = _drawn_segments(fs)
    adrift = []
    upright = fs.stream_labels.enclosure in UPRIGHT_ENCLOSURES
    for label in labels:
        along = _axis(label, segs.get(label.name, []), upright)
        runs = _runs(segs.get(label.name, []), along)
        assert runs, f"{name}: {label.name} lies along no run of its own line"
        share = _alongness(label.box, along, runs)
        if share <= 0.5 and label.leader is None:
            adrift.append(f"{label.name} has its own line beside {share:.0%} of it and no leader")
    assert not adrift, f"{name}: " + "; ".join(adrift)


@pytest.mark.parametrize("name", list(CORPUS), ids=list(CORPUS))
def test_a_leader_lands_on_the_line_it_names(sheets, name):
    """Check that a leader lands on the line it names (ISO 15519-1 §6.4)."""
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
    """Check that a leader is oblique (ISO 15519-1 §12.1)."""
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
    """Check that a leader cuts nothing the label was dodging."""
    fs, labels = sheets[name]
    boxes = [unit_box(u, u.frame) for u in fs.units if u.frame is not None]
    ink = _ink(fs, "vertical")
    segs = _drawn_segments(fs)
    cutting = []
    for label in labels:
        if label.leader is None:
            continue
        # A leader ends on its own line, so that line's ink is not something it cuts.
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
    """Check that the corpus still draws a leader."""
    drawn = {name: sum(1 for lab in labels if lab.leader) for name, (_fs, labels) in sheets.items()}
    assert drawn["crowded_number"] >= 1, drawn
    assert sum(drawn.values()) >= 2, drawn


def test_along_is_more_than_half_the_words_and_nothing_about_the_gap():
    """Check that ``_along`` needs over half the words beside a run, whatever the gap."""
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
    """Check that a leader is drawn only where the line is not beside the words."""
    over, under = [], []
    for name, (fs, labels) in sheets.items():
        segs = _drawn_segments(fs)
        upright = fs.stream_labels.enclosure in UPRIGHT_ENCLOSURES
        for label in labels:
            along = _axis(label, segs.get(label.name, []), upright)
            runs = _runs(segs.get(label.name, []), along)
            share = _alongness(label.box, along, runs)
            if share > 0.5 and label.leader is not None:
                over.append(f"{name}/{label.name} at {share:.0%}")
            if share <= 0.5 and label.leader is None:
                under.append(f"{name}/{label.name} at {share:.0%}")
    assert not over, "led although written along its line: " + "; ".join(over)
    assert not under, "not written along its line and not led: " + "; ".join(under)


def test_the_p_and_id_needs_exactly_one_leader(sheets):
    """Check that the P&ID needs exactly one leader."""
    _fs, labels = sheets["11_ethanol_pid"]
    led = sorted(lab.name for lab in labels if lab.leader)
    assert led == ["AE-304-150-80-SS"]


def test_a_leader_leaves_the_lettering_and_not_the_paper_beside_it(sheets):
    """Check that a leader leaves the lettering and not the paper beside it."""
    off_the_words = []
    for name, (_fs, labels) in sheets.items():
        for label in labels:
            if label.leader is None:
                continue
            (x0, y0), _end = label.leader
            box = label.box
            # The tail's along-axis coordinate has to lie on the lettering, not the padding.
            at, lo, hi = (y0, box[1], box[3]) if label.turned else (x0, box[0], box[2])
            keep = min(13.0 / 2, (hi - lo) / 4)
            if not (lo + keep - TOL <= at <= hi - keep + TOL):
                off_the_words.append(
                    f"{name}/{label.name} leaves at {at:.1f} of {lo:.1f}..{hi:.1f}"
                )
    assert not off_the_words, "; ".join(off_the_words)
