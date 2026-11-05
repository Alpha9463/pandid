"""Test line-weight ladder, renderer output, and clearance contracts."""

import math
import re
from pathlib import Path
from typing import Any

import pytest

from _render_cases import copy_settled_case
from pandid import Flowsheet, units
from pandid.render.svg import FLANGE_GAP
from pandid.render.symbols import ARROWHEAD, MIN_HEAD_CLEARANCE
from pandid.streams import SIGNAL_KINDS
from test_line_weight import drawn_pens

UNIT_MM = 0.25
_LINE_GROUPS = ("streams", "instrument_taps", "units")
WIDTH_CASES = (
    "09_ethanol_pfd",
    "10_ethanol_pid",
    "11_block_flow_diagram",
    "17_fixed_bed_recycle",
)

ROOT = Path(__file__).resolve().parent.parent


def _quantised(width: float) -> float:
    """Round a pen width to the stencil precision."""
    return round(width, 2)


def _renderer_widths(svg: str) -> set[float]:
    """Return the widths selected by the SVG renderer."""
    out: set[float] = set()
    by_symbol: dict[str, float] = {}
    for where, lo, _hi in drawn_pens(svg):
        if where in _LINE_GROUPS:
            out.add(_quantised(lo))
        elif where.startswith("sym_"):
            by_symbol[where] = max(by_symbol.get(where, 0.0), lo)
    return out | {_quantised(w) for w in by_symbol.values()}


def _streams_group(svg: str) -> str:
    """Return the SVG group containing process streams."""
    start = svg.index('<g id="streams">')
    return svg[start : svg.index("</g>", start)]


def _stream_pens(svg: str) -> set[float]:
    """Return widths used by stream path elements."""
    return {
        _quantised(float(w))
        for w in re.findall(r'<path [^>]*stroke-width="([\d.]+)"', _streams_group(svg))
    }


def _two_unit_sheet() -> Flowsheet:
    """Build a flowsheet containing material and signal lines."""
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


def test_the_ladder_stands_in_the_ratio_6_2_states() -> None:
    """Check the configured line-weight ladder ratios."""
    from pandid.render.weights import LineWeight

    main = LineWeight.MAIN_FLOW.width
    equipment = LineWeight.EQUIPMENT.width
    detail = LineWeight.DETAIL.width

    assert main / equipment == pytest.approx(1.0)
    assert equipment / detail == pytest.approx(2.0)
    assert main / detail == pytest.approx(2.0)
    assert len(LineWeight) == 3
    assert LineWeight.MAIN_FLOW is not LineWeight.EQUIPMENT
    assert min(rung.width for rung in LineWeight) == detail


def test_each_rung_is_its_own_multiple_of_the_grid_module() -> None:
    """Check that line weights derive from the grid module."""
    from pandid.render.weights import M, LineWeight

    assert M * UNIT_MM == pytest.approx(2.5)
    assert LineWeight.MAIN_FLOW.width * UNIT_MM == pytest.approx(0.5)
    assert LineWeight.EQUIPMENT.width * UNIT_MM == pytest.approx(0.5)
    assert LineWeight.DETAIL.width * UNIT_MM == pytest.approx(0.25)


def test_every_width_survives_the_formatting_it_is_written_with() -> None:
    """Check that formatted widths round-trip exactly."""
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
    """Check renderer source selects stroke widths from the ladder."""
    bad: list[str] = []
    for name in ("svg.py", "drawio.py"):
        text = (ROOT / "pandid" / "render" / name).read_text(encoding="utf-8")
        for n, line in enumerate(text.splitlines(), 1):
            if "m.group(" in line:
                continue
            if re.search(r'stroke-width="[^"]*\d', line) or re.search(
                r"strokeWidth=[^;\"']*\d", line
            ):
                bad.append(f"pandid/render/{name}:{n}: {line.strip()}")
    assert not bad, "a width written as a literal instead of chosen from the ladder:\n" + "\n".join(
        bad
    )


def test_a_main_flow_line_is_drawn_at_the_weight_of_the_equipment_it_enters() -> None:
    """Check material lines match equipment outline weight."""
    fs = _two_unit_sheet()
    svg = fs.to_svg()
    run = max(_stream_pens(svg))
    outline = _quantised(
        max(lo for where, lo, _hi in drawn_pens(svg) if where.startswith("sym_vessel"))
    )
    assert run / outline == pytest.approx(1.0)


def test_a_control_line_is_drawn_at_half_the_run_it_reads() -> None:
    """Check signal lines use half the material-line weight."""
    fs = _two_unit_sheet()
    svg = fs.to_svg()
    pens = sorted(_stream_pens(svg))
    assert len(pens) == 2, f"expected a run and a signal, got {pens}"
    signal, run = pens
    assert run / signal == pytest.approx(2.0)


@pytest.mark.parametrize("name", WIDTH_CASES, ids=WIDTH_CASES)
def test_every_width_a_sheet_draws_on_is_a_rung_of_one_ladder(
    settled_gallery: dict[str, tuple[Flowsheet, dict[str, Any]]], name: str
) -> None:
    """Check representative sheets use only ladder widths, none under the floor."""
    fs, kwargs = copy_settled_case(settled_gallery, name)
    widths = _renderer_widths(fs.to_svg(**kwargs))
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
    for width in widths:
        assert width * UNIT_MM >= 0.25 - 1e-9, (
            f"{name}: a line drawn at {width:g} units is {width * UNIT_MM:.3f} mm, "
            f"under the floor ISO 10628-1 5.3.1 sets"
        )


@pytest.mark.parametrize("name", WIDTH_CASES, ids=WIDTH_CASES)
def test_the_export_puts_every_run_on_the_rung_the_sheet_puts_it_on(
    settled_gallery: dict[str, tuple[Flowsheet, dict[str, Any]]], name: str
) -> None:
    """Check Draw.io preserves representative stream-weight ratios."""
    from test_drawio import _DRAWIO_KWARGS, _drawio_cells, _style

    fs, kwargs = copy_settled_case(settled_gallery, name)
    drawn = [
        float(w)
        for w in re.findall(
            r'<path [^>]*stroke-width="([\d.]+)"', _streams_group(fs.to_svg(**kwargs))
        )
    ]
    drawio_fs, drawio_kwargs = copy_settled_case(settled_gallery, name)
    cells = _drawio_cells(
        drawio_fs, {k: v for k, v in drawio_kwargs.items() if k in _DRAWIO_KWARGS}
    )
    exported = [
        float(_style(cells[f"s{n}"])["strokeWidth"])
        for n in range(len(drawn))
        if f"s{n}" in cells and "strokeWidth" in _style(cells[f"s{n}"])
    ]
    assert len(exported) == len(drawn) > 0, (
        f"{name}: the sheet drew {len(drawn)} runs and the export wrote {len(exported)}"
    )
    for stream, width in zip(fs.streams, drawn):
        want = 1.0 if stream.kind in SIGNAL_KINDS else 2.0
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


def test_a_flange_pair_leaves_the_paper_5_3_2_asks_between_two_parallel_lines() -> None:
    """Check flange faces meet the required clearance."""
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
    """Check arrowhead clearance tracks the material-line weight."""
    fs = _two_unit_sheet()
    run = max(_stream_pens(fs.to_svg()))
    assert MIN_HEAD_CLEARANCE == pytest.approx(2 * run)


def test_a_leader_head_is_a_size_and_does_not_follow_a_rung() -> None:
    """Check leader-head size remains independent of the ladder."""
    from pandid.render.svg import _LEADER_HEAD

    assert ARROWHEAD / _LEADER_HEAD == pytest.approx(2.0)


def _main_and_subsidiary() -> Flowsheet:
    """Build a sheet with two main lines and a subsidiary drain line."""
    fs = Flowsheet("subsidiary")
    feed = fs.add(units.Feed("F"))
    vessel = fs.add(units.Vessel("V-1"))
    product = fs.add(units.Product("P"))
    sump = fs.add(units.Product("DR"))
    fs.connect(feed.outlet, vessel.inlet)
    fs.connect(vessel.outlet, product.inlet)
    fs.connect(vessel.drain, sump.inlet, subsidiary=True)
    return fs


def _wide_main_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    """Put the main-flow rung at 0.4 M so it differs from the equipment rung."""
    from pandid.render import weights

    monkeypatch.setitem(weights._MODULES, weights.LineWeight.MAIN_FLOW, 0.4)


def test_a_subsidiary_line_is_on_the_equipment_rung() -> None:
    """Check each stream's rung: main flow, subsidiary and signal."""
    from pandid.render.svg import _stream_rung
    from pandid.render.weights import LineWeight

    fs = _main_and_subsidiary()
    signal = _two_unit_sheet().streams[-1]
    assert [_stream_rung(s) for s in fs.streams] == [
        LineWeight.MAIN_FLOW,
        LineWeight.MAIN_FLOW,
        LineWeight.EQUIPMENT,
    ]
    assert _stream_rung(signal) is LineWeight.DETAIL


def test_a_subsidiary_line_is_drawn_at_the_width_of_its_rung(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Check the SVG draws a subsidiary line at the equipment width."""
    from pandid.render.weights import LineWeight

    _wide_main_flow(monkeypatch)
    svg = _main_and_subsidiary().to_svg()
    pens = [
        float(w) for w in re.findall(r'<path [^>]*stroke-width="([\d.]+)"', _streams_group(svg))
    ]
    main, equipment = LineWeight.MAIN_FLOW.width, LineWeight.EQUIPMENT.width
    assert main == 2 * equipment
    assert pens == [main, main, equipment]


def test_the_export_draws_a_subsidiary_line_at_the_width_of_its_rung(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Check draw.io exports a subsidiary line at the equipment width."""
    from test_drawio import _drawio_cells, _style

    _wide_main_flow(monkeypatch)
    cells = _drawio_cells(_main_and_subsidiary(), {})
    widths = [float(_style(cells[f"s{n}"])["strokeWidth"]) for n in range(3)]
    assert widths[0] == widths[1] == pytest.approx(2 * widths[2])


def test_a_valve_put_on_a_subsidiary_line_keeps_both_parts_subsidiary() -> None:
    """Check a line split by on= stays subsidiary on each segment."""
    fs = _main_and_subsidiary()
    fs.add(units.Valve("HV-1"), on=fs.streams[-1])
    assert [s.subsidiary for s in fs.streams] == [False, False, True, True]


def test_subsidiary_is_refused_on_a_signal_line_and_the_sheet_is_unchanged() -> None:
    """Check subsidiary=True on a signal line raises and leaves the sheet as it was."""
    fs = Flowsheet("refused")
    lt = fs.add(units.Instrument("LT-1"))
    lc = fs.add(units.Instrument("LIC-1"))
    before = fs.to_dict()
    with pytest.raises(ValueError, match="leave subsidiary out") as caught:
        fs.connect(lt.sig_out, lc.sig_in, kind="electric", subsidiary=True)
    assert "LT-1.sig_out" in str(caught.value)
    assert fs.to_dict() == before
    assert fs.streams == []
    assert lt.sig_out.stream is None and lc.sig_in.stream is None
