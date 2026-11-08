"""Check the flow element variants and the orifice plate they share."""

import re

import pytest

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
