"""Check the flow element variants and the orifice plate they share."""

import re

import pytest
from marks import assert_inked
from test_blinds import _drawio_fill, _fill_at

from pandid import Feed, Fitting, FlowElement, Flowsheet, Product
from pandid.portgeom import outward_dir
from pandid.render.symbols import default_registry

#: Flow element variants that draw a principle of their own.
NEW = ("orifice", "magnetic", "ultrasonic_clamp_on", "thermal_mass", "flume", "weir")


@pytest.mark.parametrize("variant", NEW)
def test_a_flow_element_draws_each_principle(variant: str):
    """Check that ``FlowElement`` takes each variant and draws its own symbol."""
    element = FlowElement("FE-1", variant=variant)
    sym = default_registry.for_unit(element)
    assert sym is default_registry.get("fitting", variant)
    assert sym.ports["inlet"][0] == 0.0
    assert sym.ports["outlet"][0] == sym.width


def test_a_metering_and_a_restriction_orifice_draw_one_plate():
    """Check that FE and RO orifices both draw the ISO 10628-2 24.8 plate."""
    metering = default_registry.for_unit(FlowElement("FE-1", variant="orifice"))
    restriction = default_registry.for_unit(Fitting("RO-1", variant="orifice"))
    assert metering is restriction
    assert metering.drawio_shape == "mxgraph.pid.fittings.orifice_plate"
    # The run passes through the disc, above the handle.
    assert metering.ports["inlet"][1] == metering.ports["outlet"][1] == metering.width / 2


def test_a_clamp_on_meter_sits_on_the_pipe():
    """Check that the clamp-on meter's run passes along the box's bottom edge."""
    sym = default_registry.get("fitting", "ultrasonic_clamp_on")
    bottom = max(float(y) for y in re.findall(r'<rect [^>]*height="([\d.]+)"', sym.svg))
    assert sym.ports["inlet"] == (0.0, bottom)
    assert sym.ports["outlet"] == (sym.width, bottom)
    assert outward_dir(*sym.ports["inlet"], sym.width, sym.height) == "W"
    assert outward_dir(*sym.ports["outlet"], sym.width, sym.height) == "E"


def test_a_line_of_the_new_flow_elements_draws_clean(tmp_path):
    """Check that every new flow element renders on a line and validates."""
    fs = Flowsheet("Flow elements")
    upstream = fs.add(Feed("Feed")).outlet
    for i, variant in enumerate(NEW, start=1):
        element = fs.add(FlowElement(f"FE-{i}", variant=variant))
        fs.connect(upstream, element.inlet)
        upstream = element.outlet
    fs.connect(upstream, fs.add(Product("Product")).inlet)
    fs.render(str(tmp_path / "fe.svg"), diagram="p&id")
    assert fs.validate() == []
    fs.render(str(tmp_path / "fe.drawio"), diagram="p&id")


#: Each element's distinguishing mark: points its ink passes through, in
#: drawing units of its box, from the construction it is drawn to.
MARKS = {
    # 24.8's disc and handle; the bore dot is checked by its fill.
    "orifice": [(5, 0), (10, 5), (5, 10), (0, 5), (5, 20), (5, 35), (6, 5)],
    # A.4.48: four turns of field coil 4 in from the top and the bottom.
    "magnetic": [
        *[(x, 4) for x in (6.5, 9.5, 12.5, 15.5, 18.5)],
        *[(x, 5.5) for x in (8, 11, 14, 17)],
        *[(x, 21) for x in (6.5, 9.5, 12.5, 15.5, 18.5)],
        *[(x, 19.5) for x in (8, 11, 14, 17)],
    ],
    # A.4.47: two wave arcs, radii 4 and 7, round the NE and SW corners.
    "ultrasonic_clamp_on": [
        (21.30, 1.53), (22.17, 2.83), (23.47, 3.70),
        (18.53, 2.68), (20.05, 4.95), (22.32, 6.47),
        (3.70, 23.47), (2.83, 22.17), (1.53, 21.30),
        (6.47, 22.32), (4.95, 20.05), (2.68, 18.53),
    ],
    # Twin probes 10 long at x = 9 and 16, each ending in a tip of radius 2.
    "thermal_mass": [(9, 5), (16, 5), (9, 14), (7, 12), (11, 12), (16, 14), (14, 12), (18, 12)],
    # Walls closing from the mouths to a throat 9 wide and 5 long, and the axis.
    "flume": [
        (5, 2.5), (10, 5), (12.5, 5), (15, 5), (20, 2.5),
        (5, 16.5), (10, 14), (12.5, 14), (15, 14), (20, 16.5),
        (5, 9.5), (12.5, 9.5), (20, 9.5),
    ],
    # The V notch cut 7.5 deep in the plate's top.
    "weir": [(6.25, 3.75), (12.5, 7.5), (18.75, 3.75)],
}  # fmt: skip


@pytest.mark.parametrize("variant", sorted(MARKS))
def test_each_flow_element_draws_its_mark(variant: str):
    """Check each element's mark is on the ink of the SVG and the draw.io export."""
    assert_inked(FlowElement("FE-1", variant=variant), MARKS[variant])


def test_the_orifice_plate_has_its_bore():
    """Check 24.8's bore dot is filled, in the SVG and the draw.io export."""
    plate = FlowElement("FE-1", variant="orifice")
    assert _fill_at(default_registry.for_unit(plate).svg, (5, 5)) == "#111"
    assert _drawio_fill(plate, (5, 5)) == "#111"
