"""Check the paddle blind and paddle spacer, ISO 10628-2 items 24.9 and 24.10."""

import xml.etree.ElementTree as ET

import pytest
from marks import _STENCILS, assert_inked, off_ink, svg_ink
from test_symbol_invariants import _IDENTITY, _apply, _compose, _parse_transform, _script

from pandid import Feed, Fitting, Flowsheet, PaddleBlind, PaddleSpacer, Product, Pump, Valve
from pandid.portgeom import axial_tap, unit_box
from pandid.render.svg import tap_lines
from pandid.render.symbols import default_registry

#: The disc on its handle, as both rows draw it in a 10 x 30 box: the
#: disc's rim at its four quarter points, and the handle down to its foot.
DISC_AND_HANDLE = [(5, 0), (10, 5), (5, 10), (0, 5), (5, 20), (5, 30)]

#: A point inside the disc, clear of its rim.
INSIDE = (5, 5)


def _fill_at(svg: str, point) -> str:
    """Return the fill of the circle or ellipse drawn round a point."""
    found = []

    def walk(el, m) -> None:
        """Look for a disc round the point under one element."""
        m = _compose(m, _parse_transform(el.get("transform", "")))
        tag = el.tag.split("}")[-1]
        if tag in ("circle", "ellipse"):
            r = float(el.get("r") or 0)
            rx, ry = float(el.get("rx") or r) * m[0], float(el.get("ry") or r) * m[3]
            cx, cy = _apply(m, float(el.get("cx", 0)), float(el.get("cy", 0)))
            if ((point[0] - cx) / rx) ** 2 + ((point[1] - cy) / ry) ** 2 < 1:
                found.append(el.get("fill", ""))
        for child in el:
            walk(child, m)

    walk(ET.fromstring(svg), _IDENTITY)
    return found[-1] if found else ""


def _drawio_fill(unit, point) -> str:
    """Return the fill draw.io paints at a point of a unit's library stencil."""
    sym = default_registry.for_unit(unit)
    package, name = sym.drawio_shape.removeprefix("mxgraph.pid.").split(".", 1)
    mx = _script("mxgraph_to_svg")
    for shape_name, el in mx.shapes_in(_STENCILS / f"{package}.xml"):
        if shape_name.replace(" ", "_").lower() == name:
            inner, w, h, _, _ = mx.convert_shape(el)
            return _fill_at(
                f"<g>{inner}</g>", (point[0] * w / sym.width, point[1] * h / sym.height)
            )
    raise AssertionError(f"{sym.drawio_shape} is not in the vendored stencils")


@pytest.mark.parametrize(
    "cls,variant", [(PaddleBlind, "paddle_blind"), (PaddleSpacer, "paddle_spacer")]
)
def test_each_class_draws_its_row(cls, variant: str):
    """Check each class draws its variant, with the run through the disc."""
    sym = default_registry.for_unit(cls("SB-1"))
    assert sym is default_registry.for_unit(Fitting("SB-2", variant=variant))
    assert (sym.width, sym.height) == (10.0, 30.0)
    assert sym.ports == {"inlet": (0.0, 5.0), "outlet": (10.0, 5.0)}


def test_the_paddle_blind_is_a_solid_disc_on_its_handle():
    """Check item 24.9's disc and handle are drawn and the disc is filled."""
    unit = PaddleBlind("SB-1")
    assert_inked(unit, DISC_AND_HANDLE)
    assert _fill_at(default_registry.for_unit(unit).svg, INSIDE) == "#111"
    assert _drawio_fill(unit, INSIDE) == "#111"


def test_the_paddle_spacer_is_a_bored_disc_on_its_handle():
    """Check item 24.10's disc and handle are drawn and the disc is left open."""
    unit = PaddleSpacer("SP-1")
    assert_inked(unit, DISC_AND_HANDLE)
    assert _fill_at(default_registry.for_unit(unit).svg, INSIDE) == "white"
    assert _drawio_fill(unit, INSIDE) == "white"


def test_a_paddle_blind_is_drawn_one_way():
    """Check a closed position is refused: the solid disc already blanks the line."""
    with pytest.raises(ValueError, match="drawn one way"):
        PaddleBlind("SB-1", normal_position="closed")


def test_a_line_through_each_draws_clean(tmp_path):
    """Check both render in a line and validate."""
    fs = Flowsheet("Blinds")
    blind = fs.add(PaddleBlind("SB-1"))
    spacer = fs.add(PaddleSpacer("SP-1"))
    fs.connect(fs.add(Feed("Feed")).outlet, blind.inlet)
    fs.connect(blind.outlet, spacer.inlet)
    fs.connect(spacer.outlet, fs.add(Product("Product")).inlet)
    fs.render(str(tmp_path / "b.svg"), diagram="p&id")
    assert fs.validate() == []
    fs.render(str(tmp_path / "b.drawio"), diagram="p&id")


@pytest.mark.parametrize("variant", ["blind", "orifice", "paddle_blind", "paddle_spacer"])
@pytest.mark.parametrize("face", ["E", "W"])
def test_a_tap_from_the_side_of_a_disc_on_a_handle_starts_on_its_ink(variant: str, face: str):
    """Check a side balloon's tap starts on the drawing, not beside the handle."""
    fs = Flowsheet("Tap")
    fitting = fs.add(Fitting("X-1", variant=variant))
    fs.connect(fs.add(Feed("Feed")).outlet, fitting.inlet)
    fs.connect(fitting.outlet, fs.add(Product("Product")).inlet)
    fs.add_instrument("PI", 1, sensing=fitting, face=face)
    fs.route()
    [(_, (tx, ty), _)] = tap_lines(fs)
    x0, y0, _, _ = unit_box(fitting, fitting.frame)
    assert not off_ink([(tx - x0, ty - y0)], svg_ink(fitting))


def test_a_turned_disc_on_a_handle_takes_side_taps_on_its_turned_axis():
    """Check a blind turned a quarter takes the axis tap from N and S, not E and W."""
    fs = Flowsheet("Turned")
    blind = fs.add(Fitting("X-1", variant="blind")).pin(orientation=90)
    fs.connect(fs.add(Feed("Feed")).outlet, blind.inlet)
    fs.connect(blind.outlet, fs.add(Product("Product")).inlet)
    fs.route()
    x0, y0, x1, y1 = unit_box(blind, blind.frame)
    centre = ((x0 + x1) / 2, (y0 + y1) / 2)
    assert axial_tap(blind, blind.frame, "N") == centre
    assert axial_tap(blind, blind.frame, "S") == centre
    assert axial_tap(blind, blind.frame, "E") is None
    assert axial_tap(blind, blind.frame, "W") is None


def test_a_side_tap_keeps_its_old_start_where_the_new_one_crosses_a_unit():
    """Check the centre start is not taken where its tap line would cross a valve."""
    fs = Flowsheet("Tap past a valve")
    blind = fs.add(Fitting("SB-1", variant="blind"))
    valve = fs.add(Valve("HV-1"))
    pump = fs.add(Pump("P-1"))
    fs.connect(fs.add(Feed("Feed")).outlet, pump.suction)
    fs.connect(pump.discharge, blind.inlet)
    fs.connect(blind.outlet, valve.inlet)
    fs.connect(valve.outlet, fs.add(Product("Product")).inlet)
    fs.add_instrument("PI", 1, sensing=blind)
    fs.to_svg(diagram="p&id")
    assert not [i for i in fs.validate() if i.code == "tap-crosses-unit"]
