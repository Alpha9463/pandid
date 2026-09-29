"""Verify rendered SVG stroke weights.

The checks cover symbol strokes, direct sheet lines, flattened export input, and
resized equipment. Each gallery sheet is rendered once for the three corpus
checks so that the assertions share identical output.
"""

import math
import re
import xml.etree.ElementTree as ET
from typing import Any

import pytest

from pandid import Flowsheet, units
from pandid.render.svg import SvgRenderer, _placement_scale
from pandid.render.symbols import Symbol, default_registry
from pandid.render.weights import LineWeight
from _render_cases import copy_settled_case, gallery

Matrix = tuple[float, float, float, float]
DrawnPen = tuple[str, float, float]

_NS = "{http://www.w3.org/2000/svg}"
_XFORM = re.compile(r"(translate|scale|rotate|matrix)\(([^)]*)\)")
_IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0)
_SHEETS = tuple(gallery.sheets())


def _mul(left: Matrix, right: Matrix) -> Matrix:
    """Compose two row-major linear transformation matrices.

    Parameters
    ----------
    left : Matrix
        Outer transformation matrix.
    right : Matrix
        Inner transformation matrix.

    Returns
    -------
    Matrix
        Matrix for applying ``right`` followed by ``left``.
    """
    return (
        left[0] * right[0] + left[1] * right[2],
        left[0] * right[1] + left[1] * right[3],
        left[2] * right[0] + left[3] * right[2],
        left[2] * right[1] + left[3] * right[3],
    )


def _linear(transform: str | None) -> Matrix:
    """Extract the linear portion of an SVG transformation list.

    Parameters
    ----------
    transform : str or None
        SVG ``transform`` attribute value.

    Returns
    -------
    Matrix
        Combined two-dimensional linear transformation matrix.
    """
    matrix = _IDENTITY
    for operation, arguments in _XFORM.findall(transform or ""):
        values = [float(value) for value in re.split(r"[,\s]+", arguments.strip()) if value]
        if operation == "translate":
            continue
        if operation == "scale":
            next_matrix = (values[0], 0.0, 0.0, values[1] if len(values) > 1 else values[0])
        elif operation == "rotate":
            angle = math.radians(values[0])
            next_matrix = (math.cos(angle), -math.sin(angle), math.sin(angle), math.cos(angle))
        else:
            next_matrix = (values[0], values[2], values[1], values[3])
        matrix = _mul(matrix, next_matrix)
    return matrix


def _pen_axes(matrix: Matrix) -> tuple[float, float]:
    """Calculate the minor and major transformed pen widths.

    Parameters
    ----------
    matrix : Matrix
        Linear transformation applied to a circular pen.

    Returns
    -------
    tuple[float, float]
        Minor and major pen widths, in ascending order.
    """
    a, b, c, d = matrix
    first = math.hypot((a + d) / 2, (c - b) / 2)
    second = math.hypot((a - d) / 2, (c + b) / 2)
    return abs(first - second), first + second


def _viewport(use: ET.Element, symbol: ET.Element) -> Matrix:
    """Calculate the scale from a ``<use>`` viewport to its symbol.

    Parameters
    ----------
    use : xml.etree.ElementTree.Element
        SVG ``<use>`` element.
    symbol : xml.etree.ElementTree.Element
        Referenced SVG ``<symbol>`` element.

    Returns
    -------
    Matrix
        Viewport scale applied to the symbol contents.
    """
    view_box = symbol.get("viewBox")
    assert view_box is not None, "symbol definitions must declare a viewBox"
    _, _, view_width, view_height = (float(value) for value in view_box.split())
    width = float(use.get("width", view_width))
    height = float(use.get("height", view_height))
    if symbol.get("preserveAspectRatio") == "none":
        return (width / view_width, 0.0, 0.0, height / view_height)
    scale = min(width / view_width, height / view_height)
    return (scale, 0.0, 0.0, scale)


def _walk(
    element: ET.Element,
    matrix: Matrix,
    symbols: dict[str, ET.Element],
    pens: list[DrawnPen],
    group: str,
) -> None:
    """Collect effective stroke widths from an SVG element tree.

    Parameters
    ----------
    element : xml.etree.ElementTree.Element
        Current SVG element.
    matrix : Matrix
        Transformation inherited from parent elements.
    symbols : dict[str, xml.etree.ElementTree.Element]
        Symbol definitions indexed by identifier.
    pens : list[DrawnPen]
        Effective widths collected during traversal.
    group : str
        Current SVG group or symbol identifier.
    """
    for child in element:
        tag = child.tag.replace(_NS, "")
        if tag in ("defs", "symbol", "marker"):
            continue
        child_matrix = _mul(matrix, _linear(child.get("transform", "")))
        if tag == "g" and child.get("id") == "drawing":
            minor, major = _pen_axes(_linear(child.get("transform", "")))
            assert math.isclose(minor, major, rel_tol=1e-9), (
                f"the page fit is not a uniform scale: {minor:.4g} by {major:.4g}"
            )
            child_matrix = matrix
        if tag == "use":
            reference = (child.get("href") or child.get(f"{_NS}href", ""))[1:]
            _walk(
                symbols[reference],
                _mul(child_matrix, _viewport(child, symbols[reference])),
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
    """Return the effective widths of all rendered SVG strokes.

    Parameters
    ----------
    svg : str
        Rendered SVG document.

    Returns
    -------
    list[DrawnPen]
        Group or symbol identifier with each stroke's minor and major widths.
    """
    root = ET.fromstring(svg)
    symbols = {element.get("id", ""): element for element in root.iter(f"{_NS}symbol")}
    pens: list[DrawnPen] = []
    _walk(root, _IDENTITY, symbols, pens, "")
    return pens


def authored_pens(symbol: Symbol) -> list[float]:
    """Return a symbol definition's declared stroke widths.

    Parameters
    ----------
    symbol : pandid.render.symbols.Symbol
        Symbol definition to inspect.

    Returns
    -------
    list[float]
        Geometric mean of each definition stroke's transformed widths.
    """
    root = ET.fromstring(f'<svg xmlns="http://www.w3.org/2000/svg">{symbol.svg}</svg>')
    pens: list[DrawnPen] = []
    _walk(root, _IDENTITY, {}, pens, "")
    return [math.sqrt(minor * major) for _, minor, major in pens]


def check_symbol_weights(flowsheet: Flowsheet, svg: str) -> None:
    """Assert that every placed equipment symbol preserves its declared pens.

    Parameters
    ----------
    flowsheet : pandid.Flowsheet
        Flowsheet that produced ``svg``.
    svg : str
        Rendered SVG document for ``flowsheet``.
    """
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
            f"{unit.name}: {identifier} draws {len(rendered)} strokes, its definition "
            f"declares {len(expected)}"
        )
        width_scale, height_scale = _placement_scale(symbol, unit)
        for index, (expected_width, (minor, major)) in enumerate(zip(expected, rendered)):
            description = f"{unit.name} ({identifier}) stroke {index}"
            assert math.isclose(minor, major, rel_tol=1e-5), (
                f"{description}: drawn {minor:.4g} by {major:.4g} after placement "
                f"at {width_scale:.4g} by {height_scale:.4g}"
            )
            assert math.isclose(minor, expected_width, rel_tol=1e-5), (
                f"{description}: expected {expected_width:.4g}, drawn {minor:.4g} "
                f"at {width_scale:.4g} by {height_scale:.4g}"
            )
        checked += 1
    assert checked, "no equipment symbols were checked"


@pytest.fixture(scope="module")
def settled_gallery_svg(
    settled_gallery: dict[str, tuple[Flowsheet, dict[str, Any]]],
) -> dict[str, tuple[Flowsheet, str]]:
    """Render every settled gallery sheet once for the corpus checks.

    Parameters
    ----------
    settled_gallery : dict[str, tuple[pandid.Flowsheet, dict[str, Any]]]
        Session-scoped settled gallery flowsheets and render options.

    Returns
    -------
    dict[str, tuple[pandid.Flowsheet, str]]
        Independent flowsheets and their rendered SVG documents by sheet name.
    """
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


@pytest.mark.parametrize("stem", _SHEETS, ids=_SHEETS)
def test_every_symbol_on_the_corpus_is_drawn_at_its_declared_weight(
    stem: str, settled_gallery_svg: dict[str, tuple[Flowsheet, str]]
) -> None:
    """Verify that all gallery equipment preserves its definition stroke widths.

    Parameters
    ----------
    stem : str
        Gallery sheet name.
    settled_gallery_svg : dict[str, tuple[pandid.Flowsheet, str]]
        Shared rendered gallery sheets.
    """
    flowsheet, svg = settled_gallery_svg[stem]
    check_symbol_weights(flowsheet, svg)


@pytest.mark.parametrize("stem", _SHEETS, ids=_SHEETS)
def test_every_line_on_the_corpus_lands_on_one_of_the_two_sheet_weights(
    stem: str, settled_gallery_svg: dict[str, tuple[Flowsheet, str]]
) -> None:
    """Verify that gallery stream and instrument lines use defined sheet weights.

    Parameters
    ----------
    stem : str
        Gallery sheet name.
    settled_gallery_svg : dict[str, tuple[pandid.Flowsheet, str]]
        Shared rendered gallery sheets.
    """
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
    """Verify that flattened gallery SVGs have only circular effective pens.

    Parameters
    ----------
    stem : str
        Gallery sheet name.
    settled_gallery_svg : dict[str, tuple[pandid.Flowsheet, str]]
        Shared rendered gallery sheets.
    """
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
    """Verify that each equipment family preserves pens across box shapes.

    Parameters
    ----------
    specimen : str
        Symbol family and optional variant under test.
    box : str
        Named width and height scaling factors.
    """
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
        for group, minor, major in drawn_pens(flowsheet.to_svg()):
            if not group.startswith("sym_valve"):
                continue
            assert minor == pytest.approx(LineWeight.DETAIL.width, rel=1e-5)
            assert major == pytest.approx(LineWeight.DETAIL.width, rel=1e-5)
            checked += 1
    assert checked, "no valve strokes were checked"
