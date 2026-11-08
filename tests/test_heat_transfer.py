"""Check the floating-head and coil-tube exchangers and the electric heater."""

import pytest
from marks import assert_inked

from pandid import (
    ElectricHeater,
    Feed,
    Flowsheet,
    HeatExchanger,
    Heater,
    Product,
    ShellAndTubeExchanger,
)
from pandid.portgeom import outward_dir
from pandid.render.symbols import default_registry


@pytest.mark.parametrize(
    "variant,shape",
    [
        ("floating_head", "mxgraph.pid.heat_exchangers.heat_exchanger_(floating_head)"),
        ("coil_tube", "mxgraph.pid.heat_exchangers.heat_exchanger_(coil_tubes)"),
    ],
)
def test_a_shell_and_tube_exchanger_draws_each_bundle(variant: str, shape: str):
    """Check that each bundle is a shell-and-tube variant with its ISO drawing."""
    sym = default_registry.for_unit(ShellAndTubeExchanger("E-1", variant=variant))
    assert sym is default_registry.for_unit(HeatExchanger("E-2", variant=variant))
    assert sym.drawio_shape == shape


def test_a_floating_head_takes_its_tube_side_through_the_channel():
    """Check that both tube nozzles are on the channel, either side of its partition."""
    sym = default_registry.get("hex", "floating_head")
    (xi, yi), (xo, yo) = sym.ports["tube_in"], sym.ports["tube_out"]
    assert xi == xo == 0.0
    assert yi < sym.height / 2 < yo
    assert outward_dir(*sym.ports["shell_in"], sym.width, sym.height) == "N"
    assert outward_dir(*sym.ports["shell_out"], sym.width, sym.height) == "S"


def test_a_coil_tube_exchanger_runs_its_tubes_head_to_head():
    """Check that the coil's tube side passes from the west head to the east one."""
    sym = default_registry.get("hex", "coil_tube")
    assert sym.ports["tube_in"] == (0.0, sym.height / 2)
    assert sym.ports["tube_out"] == (sym.width, sym.height / 2)


def test_an_electric_heater_is_powered_through_its_terminal_box():
    """Check the electric heater's process nozzles and its supply."""
    sym = default_registry.for_unit(ElectricHeater("H-1"))
    assert sym is default_registry.for_unit(Heater("H-2", variant="electric"))
    assert sym.drawio_shape == "mxgraph.pid.heat_exchangers.electric_heater"
    w, h = sym.width, sym.height
    assert outward_dir(*sym.ports["utility_in"], w, h) == "W"
    assert outward_dir(*sym.ports["inlet"], w, h) == "S"
    assert outward_dir(*sym.ports["outlet"], w, h) == "N"


def test_each_new_drawing_draws_clean(tmp_path):
    """Check that the new exchangers and the heater render on lines and validate."""
    fs = Flowsheet("Heat transfer")
    for i, variant in enumerate(("floating_head", "coil_tube"), start=1):
        hx = fs.add(ShellAndTubeExchanger(f"E-{i}", variant=variant))
        fs.connect(fs.add(Feed(f"P-{i}")).outlet, hx.tube_in)
        fs.connect(hx.tube_out, fs.add(Product(f"P-{i} out")).inlet)
        fs.connect(fs.add(Feed(f"CW-{i}")).outlet, hx.shell_in)
        fs.connect(hx.shell_out, fs.add(Product(f"CW-{i} out")).inlet)
    heater = fs.add(ElectricHeater("H-1"))
    fs.connect(fs.add(Feed("Cold")).outlet, heater.inlet)
    fs.connect(heater.outlet, fs.add(Product("Hot")).inlet)
    fs.render(str(tmp_path / "hx.svg"), diagram="p&id")
    assert fs.validate() == []
    fs.render(str(tmp_path / "hx.drawio"), diagram="p&id")


def _along(path) -> list:
    """Return a polyline's corners and the quarter points of each stroke."""
    return path + [
        (ax + t * (bx - ax), ay + t * (by - ay))
        for (ax, ay), (bx, by) in zip(path, path[1:])
        for t in (0.25, 0.75)
    ]


def test_the_floating_head_and_the_channel_partition_are_drawn():
    """Check item 3.4's floating-head cover and pass partition, in both exports."""
    cover = [(79, 5), (85, 5), (85, 25), (79, 25), (82, 5), (85, 15), (82, 25)]
    partition = [(0, 15), (7.5, 15), (15, 15)]
    tubes = [(47, 7.5), (47, 12.5), (47, 17.5), (47, 22.5)]
    assert_inked(
        ShellAndTubeExchanger("E-1", variant="floating_head"),
        cover + partition + tubes,
    )


def test_the_coil_runs_between_the_tubesheets():
    """Check item 3.7's coil, corner by corner, in both exports."""
    coil = [(15, 15), (26, 15), (29, 7.5), (35, 22.5), (41, 7.5), (47, 22.5)]
    coil += [(53, 7.5), (58, 22.5), (65, 7.5), (71, 22.5), (74, 15), (85, 15)]
    assert_inked(ShellAndTubeExchanger("E-1", variant="coil_tube"), _along(coil))


def test_the_electric_heater_draws_its_terminal_box_and_elements():
    """Check item 3.13's E, its three leads and its three elements, in both exports."""
    letter = [(25, 40), (15, 40), (15, 60), (25, 60), (15, 50), (22, 50)]
    leads = [(55, 25), (55, 50), (55, 75)]
    elements = [
        (x, y + dy)
        for y in (17.5, 42.5, 67.5)
        for x in (70, 85, 100, 115, 130)
        for dy in (0, 7.5, 15)
    ]
    assert_inked(ElectricHeater("H-1"), letter + leads + elements)
