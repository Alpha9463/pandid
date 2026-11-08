"""Check the screw compressor, ISO 10628-2 item 16.8, beside the rotary one."""

from pandid import (
    Compressor,
    Feed,
    Flowsheet,
    Product,
    RotaryCompressor,
    ScrewCompressor,
)
from pandid.render.symbols import default_registry

#: Table 2's grid module, in drawing units.
M = 10.0


def test_a_screw_compressor_draws_item_16_8():
    """Check that ``ScrewCompressor`` draws its own ISO drawing on the 16.1 outline."""
    sym = default_registry.for_unit(ScrewCompressor("K-1"))
    assert sym is default_registry.for_unit(Compressor("K-2", variant="screw"))
    assert sym.iso_reg == "X8161"
    assert (sym.width, sym.height) == (6 * M, 6 * M)
    assert sym.ports == {"suction": (0.0, 3 * M), "discharge": (6 * M, 3 * M)}


def test_the_rotary_compressor_is_not_the_screw():
    """Check that ``RotaryCompressor`` keeps its own two-rotor drawing."""
    rotary = default_registry.for_unit(RotaryCompressor("K-1"))
    assert rotary is not default_registry.get("compressor", "screw")
    assert rotary.drawio_shape == "mxgraph.pid.compressors.rotary_compressor"


def test_a_line_through_a_screw_compressor_draws_clean(tmp_path):
    """Check that a screw compressor renders on a line and validates."""
    fs = Flowsheet("Screw")
    k = fs.add(ScrewCompressor("K-1"))
    fs.connect(fs.add(Feed("Air")).outlet, k.suction)
    fs.connect(k.discharge, fs.add(Product("Plant air")).inlet)
    fs.render(str(tmp_path / "k.svg"), diagram="p&id")
    assert fs.validate() == []
    fs.render(str(tmp_path / "k.drawio"), diagram="p&id")
