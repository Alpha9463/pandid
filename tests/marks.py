"""Find where a unit's drawing puts ink, as the SVG and draw.io emit it.

A mark guard states points a drawing's distinguishing mark passes
through, from the standard's construction, and checks each lies on
the ink of both exports.
"""

import pathlib

from test_drawio import _inline_stencil, _model, _stencil_svg, _style
from test_symbol_invariants import _collect_segments, _nearest_distance, _script

from pandid import Flowsheet
from pandid.render.symbols import default_registry

#: Furthest a stated point may lie from the ink drawn for it.
INK_TOL = 0.3

_STENCILS = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "vendor_data" / "drawio"


def svg_ink(unit) -> list:
    """Return the segments the SVG symbol definition draws for a unit."""
    return _collect_segments(default_registry.for_unit(unit).svg)


def drawio_ink(unit) -> list:
    """Return the segments the draw.io export draws, in the symbol's box.

    An inline stencil is decoded; a library stencil is read from the
    vendored stencil file and scaled from its box to the symbol's. A
    built-in shape counts as the cell's box.
    """
    sym = default_registry.for_unit(unit)
    fs = Flowsheet("ink")
    fs.add(unit)
    cell = next(c for c in _model(fs, check=False).iter("mxCell") if c.get("value") == unit.name)
    shape = _style(cell).get("shape", "")
    stencil = _inline_stencil(shape)
    if stencil is not None:
        return _collect_segments(_stencil_svg(stencil))
    if not shape.startswith("mxgraph.pid."):
        # A built-in shape: at most the cell's box.
        w, h = sym.width, sym.height
        corners = [(0.0, 0.0), (w, 0.0), (w, h), (0.0, h)]
        return list(zip(corners, corners[1:] + corners[:1]))
    mx = _script("mxgraph_to_svg")
    package, name = shape.removeprefix("mxgraph.pid.").split(".", 1)
    for shape_name, el in mx.shapes_in(_STENCILS / f"{package}.xml"):
        if shape_name.replace(" ", "_").lower() == name:
            inner, w, h, _, _ = mx.convert_shape(el)
            sx, sy = sym.width / w, sym.height / h
            return [
                ((ax * sx, ay * sy), (bx * sx, by * sy))
                for (ax, ay), (bx, by) in _collect_segments(f"<g>{inner}</g>")
            ]
    raise AssertionError(f"{shape} is not in the vendored stencils")


def off_ink(points, segments) -> list:
    """Return the stated points farther than ``INK_TOL`` from any segment."""
    return [p for p in points if _nearest_distance(p, segments) > INK_TOL]


def assert_inked(unit, points) -> None:
    """Check that every stated point lies on the unit's ink in both exports."""
    for export, segments in (("SVG", svg_ink(unit)), ("draw.io", drawio_ink(unit))):
        missing = off_ink(points, segments)
        assert not missing, f"{unit.name}: the {export} drawing has no ink at {missing}"
