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
    wave_points,
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


def _on_curve(d: str) -> list[tuple[float, float]]:
    """Return the start point and every curve end of a path of ``M`` and ``Q``."""
    numbers = [float(n) for n in re.findall(r"-?[\d.]+", d)]
    assert d.lstrip().startswith("M") and set(re.findall(r"[A-Za-z]", d)) == {"M", "Q"}
    points = [(numbers[0], numbers[1])]
    for i in range(2, len(numbers), 4):
        points.append((numbers[i + 2], numbers[i + 3]))
    return points


def _off_route(p: tuple[float, float], route: list[tuple[float, float]]) -> float:
    """Return a point's distance from a polyline."""
    best = math.inf
    for (ax, ay), (bx, by) in zip(route, route[1:]):
        dx, dy = bx - ax, by - ay
        t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / (dx * dx + dy * dy)))
        best = min(best, math.hypot(p[0] - ax - t * dx, p[1] - ay - t * dy))
    return best


def test_a_wireless_line_is_a_wave_along_its_route(wireless):
    """Draw the ISA wireless signal: a wave on the route, ending on both ports."""
    route = stream_polyline(wireless.streams[0])
    assert len(route) >= 3, "the fixture stopped turning a corner"
    body = _streams(wireless.to_svg(check=False))
    (d,) = re.findall(r'<path d="([^"]+)"', body)
    points = _on_curve(d)
    assert points[0] == pytest.approx(route[0]) and points[-1] == pytest.approx(route[-1])
    # Many half-waves, each starting and ending near the route.
    assert len(points) > 10
    assert max(_off_route(p, route) for p in points) <= 2 * WAVE_RISE
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
    """Export the wave as a curved edge whose points are the sheet's control points."""
    edge = _drawio_cells(wireless)["s0"]
    style = edge.get("style") or ""
    assert "curved=1" in style and "dashed" not in style
    drawn = [(float(p.get("x", 0)), float(p.get("y", 0))) for p in edge.iter("mxPoint")]
    crests = wave_points(stream_polyline(wireless.streams[0]))[1:-1]
    assert len(drawn) == len(crests) > 10
    # The same wave, moved and scaled onto the page.
    (x0, y0), (x1, y1) = drawn[0], drawn[-1]
    (a0, b0), (a1, b1) = crests[0], crests[-1]
    scale = math.hypot(x1 - x0, y1 - y0) / math.hypot(a1 - a0, b1 - b0)
    for (x, y), (a, b) in zip(drawn, crests):
        assert (x - x0, y - y0) == pytest.approx(((a - a0) * scale, (b - b0) * scale), abs=0.05)


@pytest.mark.parametrize("kind", ["hydraulic", "wireless"])
def test_a_signal_kind_reads_back_from_its_spec(kind):
    """Keep a hydraulic or wireless line's kind through ``to_dict`` and ``from_dict``."""
    fs = Flowsheet("spec")
    a = fs.add(units.Instrument("LT", 101))
    b = fs.add(units.Instrument("LIC", 101))
    fs.connect(a, b, kind=kind)
    assert [s.kind for s in Flowsheet.from_dict(fs.to_dict()).streams] == [kind]
