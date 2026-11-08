"""Check the hydraulic and wireless signal lines in SVG and draw.io."""

import math
import re
import xml.etree.ElementTree as ET

import pytest

from pandid import Flowsheet, units
from pandid.render.svg import (
    HATCH_ARM,
    HYDRAULIC_FOOT,
    WAVE_RISE,
    signal_marks,
    stream_polyline,
)


def _sheet(kind: str) -> Flowsheet:
    """Return a routed sheet with one signal line of ``kind`` turning a corner."""
    fs = Flowsheet(kind)
    valve = fs.add(units.Valve("FV-101", variant="control")).pin(x=400, y=300)
    pic = fs.add_instrument("PIC", 101, display="central").pin(x=100, y=100)
    fs.connect(pic.sig_out, valve.actuator, kind=kind)
    fs.route()
    return fs


@pytest.fixture(scope="module")
def hydraulic() -> Flowsheet:
    """Return the hydraulic sheet."""
    return _sheet("hydraulic")


@pytest.fixture(scope="module")
def wireless() -> Flowsheet:
    """Return the wireless sheet."""
    return _sheet("wireless")


def _streams(svg: str) -> str:
    """Return the body of the sheet's streams group."""
    return svg.split('<g id="streams">', 1)[1].split("</g>", 1)[0]


def _strokes(svg: str) -> list[tuple[float, float, float, float]]:
    """Return every ``<line>`` drawn in the streams group."""
    pattern = r'<line x1="([-\d.]+)" y1="([-\d.]+)" x2="([-\d.]+)" y2="([-\d.]+)"'
    return [
        (float(a), float(b), float(c), float(d))
        for a, b, c, d in re.findall(pattern, _streams(svg))
    ]


def test_a_hydraulic_line_is_solid_with_a_footed_stroke_at_each_mark(hydraulic):
    """Draw ISO 15519-2 A.1.08: a slash across the line and a foot along it."""
    marks = signal_marks(stream_polyline(hydraulic.streams[0]))
    assert len(marks) >= 2, "the fixture stopped exercising the marks"
    svg = hydraulic.to_svg(check=False)
    assert "stroke-dasharray" not in _streams(svg).split("<line", 1)[0]
    strokes = _strokes(svg)
    assert len(strokes) == 2 * len(marks)
    along, across = HATCH_ARM
    for (sx1, sy1, sx2, sy2), (fx1, fy1, fx2, fy2), mark in zip(strokes[::2], strokes[1::2], marks):
        assert math.hypot(sx2 - sx1, sy2 - sy1) == pytest.approx(
            2 * math.hypot(along, across), abs=0.2
        )
        # The slash is centred on the line.
        assert ((sx1 + sx2) / 2, (sy1 + sy2) / 2) == pytest.approx((mark.x, mark.y), abs=0.1)
        # The foot leaves the slash's first end and runs along the line, off it.
        assert (fx1, fy1) == pytest.approx((sx1, sy1), abs=0.1)
        assert math.hypot(fx2 - fx1, fy2 - fy1) == pytest.approx(HYDRAULIC_FOOT, abs=0.1)
        if mark.horizontal:
            assert fy1 == fy2 and abs(fy1 - mark.y) == pytest.approx(across, abs=0.1)
        else:
            assert fx1 == fx2 and abs(fx1 - mark.x) == pytest.approx(across, abs=0.1)


def _curves(d: str) -> list[tuple[tuple[float, float], ...]]:
    """Return each quadratic of a path of ``M`` and ``Q`` as its start, control and end."""
    assert d.lstrip().startswith("M") and set(re.findall(r"[A-Za-z]", d)) == {"M", "Q"}
    numbers = [float(n) for n in re.findall(r"-?[\d.]+", d)]
    points = list(zip(numbers[::2], numbers[1::2]))
    return [(points[i], points[i + 1], points[i + 2]) for i in range(0, len(points) - 2, 2)]


def _sides(
    points: list[tuple[float, float]], route: list[tuple[float, float]], clear: float
) -> list[list[float]]:
    """Return each point's signed offset from the run it lies beside, run by run.

    A point nearer than ``clear`` to a corner or an end of the route is left out.
    """
    runs: list[list[float]] = [[] for _ in route[1:]]
    for px, py in points:
        offsets = []
        for (ax, ay), (bx, by) in zip(route, route[1:]):
            span = math.hypot(bx - ax, by - ay)
            along = ((px - ax) * (bx - ax) + (py - ay) * (by - ay)) / span
            across = ((bx - ax) * (py - ay) - (by - ay) * (px - ax)) / span
            offsets.append((abs(across) if clear <= along <= span - clear else math.inf, across))
        k = min(range(len(offsets)), key=lambda i: offsets[i][0])
        if offsets[k][0] < math.inf:
            runs[k].append(offsets[k][1])
    return [run for run in runs if run]


def _assert_waves(runs: list[list[float]], rise: float) -> None:
    """Check each run's offsets alternate side and reach ``rise`` off the line."""
    assert sum(len(run) for run in runs) > 10, "too few crests to call it a wave"
    for run in runs:
        assert min(abs(o) for o in run) >= rise
        assert all(a * b < 0 for a, b in zip(run, run[1:])), f"not alternating: {run}"


def test_a_wireless_line_is_a_wave_along_its_route(wireless):
    """Draw the ISA wireless signal: a wave either side of the route, ending on both ports."""
    route = stream_polyline(wireless.streams[0])
    assert len(route) >= 3, "the fixture stopped turning a corner"
    body = _streams(wireless.to_svg(check=False))
    (d,) = re.findall(r'<path d="([^"]+)"', body)
    curves = _curves(d)
    assert curves[0][0] == pytest.approx(route[0]) and curves[-1][2] == pytest.approx(route[-1])
    # Each curve's middle, a quarter from each end and half from its control.
    crests = [
        (0.25 * a[0] + 0.5 * c[0] + 0.25 * b[0], 0.25 * a[1] + 0.5 * c[1] + 0.25 * b[1])
        for a, c, b in curves
    ]
    _assert_waves(_sides(crests, route, 3 * WAVE_RISE), 0.9 * WAVE_RISE)
    assert "<line" not in body and "stroke-dasharray" not in body


def _drawio_cells(fs: Flowsheet) -> dict[str, ET.Element]:
    """Index the exported cells by identifier."""
    root = ET.fromstring(fs.to_drawio(check=False))
    return {c.get("id", ""): c for c in root.iter("mxCell")}


def test_a_hydraulic_line_exports_its_marks_to_drawio(hydraulic):
    """Export each mark as a slash and a foot, two line cells on the edge."""
    marks = signal_marks(stream_polyline(hydraulic.streams[0]))
    cells = _drawio_cells(hydraulic)
    on_edge = [c for c in cells.values() if c.get("parent") == "s0"]
    assert len(on_edge) == 2 * len(marks)
    assert all("shape=line" in (c.get("style") or "") for c in on_edge)
    assert "dashed" not in (cells["s0"].get("style") or "")


def test_a_wireless_line_exports_as_a_curved_edge_through_the_wave(wireless):
    """Export the wave as a curved edge whose points swing either side of the route."""
    cells = _drawio_cells(wireless)
    edge = cells["s0"]
    style = edge.get("style") or ""
    assert "curved=1" in style and "dashed" not in style
    # The route on the page, placed by the balloon's own cell.
    pic = next(u for u in wireless.units if u.name == "PIC-101")
    frame = pic.frame
    assert frame is not None
    cell = next(c for c in cells.values() if (c.get("value") or "").endswith("PIC<br>101</div>"))
    box = cell.find("mxGeometry")
    assert box is not None
    scale = float(box.get("width", 0)) / frame.w
    x0, y0 = float(box.get("x", 0)) - frame.x * scale, float(box.get("y", 0)) - frame.y * scale
    route = [(x0 + x * scale, y0 + y * scale) for x, y in stream_polyline(wireless.streams[0])]
    drawn = [(float(p.get("x", 0)), float(p.get("y", 0))) for p in edge.iter("mxPoint")]
    # Each point is the control of a curve that rises half as far.
    _assert_waves(_sides(drawn, route, 3 * WAVE_RISE * scale), 1.8 * WAVE_RISE * scale)


@pytest.mark.parametrize("kind", ["hydraulic", "wireless"])
def test_a_signal_kind_reads_back_from_its_spec(kind):
    """Keep a hydraulic or wireless line's kind through ``to_dict`` and ``from_dict``."""
    fs = Flowsheet("spec")
    a = fs.add(units.Instrument("LT", 101))
    b = fs.add(units.Instrument("LIC", 101))
    fs.connect(a, b, kind=kind)
    assert [s.kind for s in Flowsheet.from_dict(fs.to_dict()).streams] == [kind]
