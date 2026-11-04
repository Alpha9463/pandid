"""Verify rendered SVG stroke weights of symbols, sheet lines, and resized equipment."""

import math
import xml.etree.ElementTree as ET
from typing import Any

import pytest

from pandid import Flowsheet, units
from pandid.render.svg import SvgRenderer, _placement_scale
from pandid.render.symbols import Symbol, default_registry
from pandid.render.weights import LineWeight
from _render_cases import SCENARIOS, copy_settled_case
from test_symbol_invariants import _IDENTITY, Matrix, _compose, _parse_transform

DrawnPen = tuple[str, float, float]

_NS = "{http://www.w3.org/2000/svg}"
_SHEETS = tuple(SCENARIOS)


def _pen_axes(matrix: Matrix) -> tuple[float, float]:
    """Calculate the minor and major transformed pen widths."""
    a, b, c, d, _, _ = matrix
    first = math.hypot((a + d) / 2, (c - b) / 2)
    second = math.hypot((a - d) / 2, (c + b) / 2)
    return abs(first - second), first + second


def _viewport(use: ET.Element, symbol: ET.Element) -> Matrix:
    """Calculate the scale from a ``<use>`` viewport to its symbol."""
    view_box = symbol.get("viewBox")
    assert view_box is not None, "symbol definitions must declare a viewBox"
    _, _, view_width, view_height = (float(value) for value in view_box.split())
    width = float(use.get("width", view_width))
    height = float(use.get("height", view_height))
    if symbol.get("preserveAspectRatio") == "none":
        return (width / view_width, 0.0, 0.0, height / view_height, 0.0, 0.0)
    scale = min(width / view_width, height / view_height)
    return (scale, 0.0, 0.0, scale, 0.0, 0.0)


def _walk(
    element: ET.Element,
    matrix: Matrix,
    symbols: dict[str, ET.Element],
    pens: list[DrawnPen],
    group: str,
) -> None:
    """Collect effective stroke widths from an SVG element tree."""
    for child in element:
        tag = child.tag.replace(_NS, "")
        if tag in ("defs", "symbol", "marker"):
            continue
        child_matrix = _compose(matrix, _parse_transform(child.get("transform", "")))
        if tag == "g" and child.get("id") == "drawing":
            minor, major = _pen_axes(_parse_transform(child.get("transform", "")))
            assert math.isclose(minor, major, rel_tol=1e-9), (
                f"the page fit is not a uniform scale: {minor:.4g} by {major:.4g}"
            )
            child_matrix = matrix
        if tag == "use":
            reference = (child.get("href") or child.get(f"{_NS}href", ""))[1:]
            _walk(
                symbols[reference],
                _compose(child_matrix, _viewport(child, symbols[reference])),
                symbols,
                pens,
                reference,
            )
            continue
        width = child.get("stroke-width")
        if width is not None and child.get("stroke", "none") != "none":
            minor, major = _pen_axes(child_matrix)
            pens.append((group, float(width) * minor, float(width) * major))
        next_group = child.get("id", group) if tag == "g" else group
        _walk(child, child_matrix, symbols, pens, next_group)


def drawn_pens(svg: str) -> list[DrawnPen]:
    """Return the effective widths of all rendered SVG strokes."""
    root = ET.fromstring(svg)
    symbols = {element.get("id", ""): element for element in root.iter(f"{_NS}symbol")}
    pens: list[DrawnPen] = []
    _walk(root, _IDENTITY, symbols, pens, "")
    return pens


def authored_pens(symbol: Symbol) -> list[float]:
    """Return a symbol definition's declared stroke widths."""
    root = ET.fromstring(f'<svg xmlns="http://www.w3.org/2000/svg">{symbol.svg}</svg>')
    pens: list[DrawnPen] = []
    _walk(root, _IDENTITY, {}, pens, "")
    return [math.sqrt(minor * major) for _, minor, major in pens]


def check_symbol_weights(flowsheet: Flowsheet, svg: str) -> None:
    """Assert that every placed equipment symbol preserves its declared pens."""
    renderer = SvgRenderer()
    by_identifier: dict[str, list[tuple[float, float]]] = {}
    for identifier, minor, major in drawn_pens(svg):
        by_identifier.setdefault(identifier, []).append((minor, major))

    checked = 0
    for unit in flowsheet.units:
        if unit.kind in ("feed", "product"):
            continue
        symbol = default_registry.for_unit(unit)
        identifier = renderer._sym_id(unit)
        assert identifier in by_identifier, f"{unit.name}: nothing uses {identifier!r}"
        trim_factor = LineWeight.DETAIL.width / LineWeight.EQUIPMENT.width if symbol.trim else 1.0
        expected = [width * trim_factor for width in authored_pens(symbol)]
        rendered = by_identifier[identifier][: len(expected)]
        assert len(rendered) == len(expected), (
            f"{unit.name}: {identifier} draws {len(rendered)} strokes, declares {len(expected)}"
        )
        width_scale, height_scale = _placement_scale(symbol, unit)
        for index, (expected_width, (minor, major)) in enumerate(zip(expected, rendered)):
            description = f"{unit.name} ({identifier}) stroke {index}"
            assert math.isclose(minor, major, rel_tol=1e-5), (
                f"{description}: {minor:.4g} by {major:.4g} at {width_scale:.4g}x{height_scale:.4g}"
            )
            assert math.isclose(minor, expected_width, rel_tol=1e-5), (
                f"{description}: drew {minor:.4g}, expected {expected_width:.4g}"
            )
        checked += 1
    assert checked, "no equipment symbols were checked"


@pytest.fixture(scope="module")
def settled_gallery_svg(
    settled_gallery: dict[str, tuple[Flowsheet, dict[str, Any]]],
) -> dict[str, tuple[Flowsheet, str]]:
    """Render every settled gallery sheet once for the corpus checks."""
    rendered: dict[str, tuple[Flowsheet, str]] = {}
    for stem in _SHEETS:
        flowsheet, options = copy_settled_case(settled_gallery, stem)
        rendered[stem] = flowsheet, flowsheet.to_svg(**options)
    return rendered


def test_every_symbol_declares_a_pen_centred_on_the_sheet_weight() -> None:
    """Verify that registered symbol definitions use the equipment-weight rung."""
    checked = 0
    for (kind, variant), symbol in sorted(default_registry._symbols.items()):
        pens = authored_pens(symbol)
        assert pens, f"{kind}/{variant} declares no strokes"
        assert math.isclose(max(pens), LineWeight.EQUIPMENT.width, rel_tol=2e-3), (
            f"{kind}/{variant}: outline {max(pens):.4g} differs from {LineWeight.EQUIPMENT.width}"
        )
        checked += 1
    assert checked > 100, f"only {checked} symbols were checked"


def test_no_symbol_draws_ink_below_the_floor_once_its_class_is_applied() -> None:
    """Verify every stencil's ink is drawn at 0,1 M or wider once its class is applied."""
    floor = LineWeight.DETAIL.width
    thin: list[str] = []
    for (kind, variant), symbol in sorted(default_registry._symbols.items()):
        ink = symbol.svg.replace('stroke="white"', 'stroke="none"')
        pens: list[DrawnPen] = []
        _walk(
            ET.fromstring(f'<svg xmlns="http://www.w3.org/2000/svg">{ink}</svg>'),
            _IDENTITY,
            {},
            pens,
            "",
        )
        ratio = LineWeight.DETAIL.width / LineWeight.EQUIPMENT.width if symbol.trim else 1.0
        drawn = min(math.sqrt(minor * major) for _, minor, major in pens) * ratio
        if drawn < floor * (1 - 2e-3):
            thin.append(f"{kind}/{variant} draws {drawn:.4g}")
    assert not thin, f"ink below the {floor:g}-unit floor: {thin}"


@pytest.mark.parametrize("stem", _SHEETS, ids=_SHEETS)
def test_every_symbol_on_the_corpus_is_drawn_at_its_declared_weight(
    stem: str, settled_gallery_svg: dict[str, tuple[Flowsheet, str]]
) -> None:
    """Verify that all gallery equipment preserves its definition stroke widths."""
    flowsheet, svg = settled_gallery_svg[stem]
    check_symbol_weights(flowsheet, svg)


@pytest.mark.parametrize("stem", _SHEETS, ids=_SHEETS)
def test_every_line_on_the_corpus_lands_on_one_of_the_two_sheet_weights(
    stem: str, settled_gallery_svg: dict[str, tuple[Flowsheet, str]]
) -> None:
    """Verify that gallery stream and instrument lines use defined sheet weights."""
    _, svg = settled_gallery_svg[stem]
    allowed_widths = {LineWeight.MAIN_FLOW.width, LineWeight.DETAIL.width}
    groups = {"streams", "instrument_taps"}
    seen = 0
    for group, minor, major in drawn_pens(svg):
        if group not in groups:
            continue
        assert minor == major, f"{stem}: {group} is {minor:.4g} by {major:.4g}"
        assert minor in allowed_widths, f"{stem}: {group} uses unsupported width {minor:.4g}"
        seen += 1
    assert seen, f"{stem} drew no stream or instrument lines"


@pytest.mark.parametrize("stem", _SHEETS, ids=_SHEETS)
def test_the_sheet_the_raster_backend_is_handed_carries_no_uneven_pen(
    stem: str, settled_gallery_svg: dict[str, tuple[Flowsheet, str]]
) -> None:
    """Verify that flattened gallery SVGs have only circular effective pens."""
    from pandid.render.export import flatten

    _, svg = settled_gallery_svg[stem]
    pens = drawn_pens(flatten(svg))
    for group, minor, major in pens:
        assert math.isclose(minor, major, rel_tol=1e-9), (
            f"{stem}: {group!r} reaches the raster backend as {minor:.4g} by {major:.4g}"
        )
    assert len(pens) > 10, f"{stem} flattened to only {len(pens)} strokes"


_SPECIMENS = {
    "valve": lambda **kwargs: units.Valve("FV-1", **kwargs),
    "vessel": lambda **kwargs: units.Vessel("V-1", **kwargs),
    "vessel/horizontal": lambda **kwargs: units.Vessel("V-2", variant="horizontal", **kwargs),
    "vessel/dome": lambda **kwargs: units.Vessel("V-3", variant="dome", **kwargs),
    "hex/kettle": lambda **kwargs: units.HeatExchanger("E-1", variant="kettle", **kwargs),
    "column/packed": lambda **kwargs: units.Column("T-1", variant="packed", **kwargs),
    "reducer": lambda **kwargs: units.Reducer("RD-1", large_end="outlet", **kwargs),
    "mixer": lambda **kwargs: units.Mixer("M-1", **kwargs),
    "instrument": lambda **kwargs: units.Instrument("PI-101", **kwargs),
}

_BOXES = {
    "natural": (1.0, 1.0),
    "twice": (2.0, 2.0),
    "smaller": (0.6, 0.6),
    "wider": (2.0, 1.0),
    "taller": (1.0, 2.5),
    "flattened": (3.0, 0.5),
}


@pytest.mark.parametrize("box", _BOXES, ids=_BOXES)
@pytest.mark.parametrize("specimen", _SPECIMENS, ids=_SPECIMENS)
def test_a_resized_unit_is_drawn_with_the_pen_its_symbol_declares(specimen: str, box: str) -> None:
    """Verify that each equipment family preserves pens across box shapes."""
    width_factor, height_factor = _BOXES[box]
    symbol = default_registry.get(*(specimen.split("/") + ["default"])[:2])
    flowsheet = Flowsheet("weights")
    flowsheet.add(
        _SPECIMENS[specimen](
            width=symbol.width * width_factor,
            height=symbol.height * height_factor,
        )
    )
    check_symbol_weights(flowsheet, flowsheet.to_svg())


def test_a_uniformly_resized_valve_draws_at_the_sheet_weight_exactly() -> None:
    """Verify that uniformly resized valves retain the detail weight exactly."""
    symbol = default_registry.get("valve", "gate")
    checked = 0
    for factor in (1.0, 2.878, 0.5, 4.0):
        flowsheet = Flowsheet("weights")
        flowsheet.add(
            units.Valve(
                "FV-1",
                variant="gate",
                width=symbol.width * factor,
                height=symbol.height * factor,
            )
        )
        for _group, minor, major in drawn_pens(flowsheet.to_svg()):
            assert minor == pytest.approx(LineWeight.DETAIL.width, rel=1e-5)
            assert major == pytest.approx(LineWeight.DETAIL.width, rel=1e-5)
            checked += 1
    assert checked, "no valve strokes were checked"
