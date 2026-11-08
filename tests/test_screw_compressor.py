"""Check the screw compressor, ISO 10628-2 item 16.8, beside the rotary one."""

from marks import assert_inked

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
    assert sym.ports == {
        "suction": (0.0, 3 * M),
        "discharge": (6 * M, 3 * M),
        "drive": (3 * M, 0.0),
    }


#: Item 16.8's screws, in modules from the centre: each screw's corners
#: and the midpoints of its strokes. The upper screw runs (-5/3, -1/3),
#: (-4/3, -2/3), (-2/3, 0), (0, -2/3), (2/3, 0), (4/3, -2/3), (5/3, -1/3);
#: the lower one is its mirror shifted by 2/3 along the axis.
_UPPER = [(-5, -1), (-4, -2), (-2, 0), (0, -2), (2, 0), (4, -2), (5, -1)]
_LOWER = [(-5, 1), (-4, 0), (-2, 2), (0, 0), (2, 2), (4, 0), (5, 1)]


def _on_screw(corners) -> list:
    """Return the corners and stroke midpoints of one screw, in drawing units."""
    thirds = corners + [
        ((ax + bx) / 2, (ay + by) / 2) for (ax, ay), (bx, by) in zip(corners, corners[1:])
    ]
    return [(3 * M + x * M / 3, 3 * M + y * M / 3) for x, y in thirds]


def test_the_screws_are_drawn_where_item_16_8_draws_them():
    """Check both screws lie on the drawn ink, in the SVG and the draw.io export."""
    assert_inked(ScrewCompressor("K-1"), _on_screw(_UPPER) + _on_screw(_LOWER))


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
