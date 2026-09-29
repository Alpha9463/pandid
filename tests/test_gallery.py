"""Test gallery assets and gallery-generator safeguards."""

import pathlib
import struct

import pytest

from _render_cases import gallery
from pandid import Flowsheet
from pandid.document import Revision, TitleBlock

ROOT = pathlib.Path(__file__).resolve().parent.parent
GALLERY = ROOT / "docs" / "gallery"


SHEETS = gallery.sheets()
REGENERATE = "    python scripts/gallery.py\n"


def _png_size(data: bytes) -> tuple[int, int]:
    """Read pixel dimensions from a PNG header.

    Parameters
    ----------
    data : bytes
        PNG file contents.

    Returns
    -------
    tuple[int, int]
        Width and height in pixels.

    Raises
    ------
    AssertionError
        If *data* does not begin with a PNG signature.
    """
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssertionError("not a PNG")
    return struct.unpack(">II", data[16:24])


def test_gallery_rasters_match_their_svg_view_boxes():
    """Keep every committed PNG matched to its SVG dimensions.

    Returns
    -------
    None
        Each raster has the configured width and its SVG aspect ratio.
    """
    for stem in SHEETS:
        png = GALLERY / f"{stem}.png"
        if not png.exists():
            pytest.fail(f"docs/gallery/{stem}.png is missing. Run\n\n{REGENERATE}", pytrace=False)
        width, height = _png_size(png.read_bytes())
        assert width == gallery.WIDTH, (
            f"{stem}.png is {width} px wide, not the gallery's {gallery.WIDTH}. Run\n\n{REGENERATE}"
        )

        svg = (GALLERY / f"{stem}.svg").read_text(encoding="utf-8")
        sheet_w, sheet_h = _viewbox(svg)
        # PNG heights may differ from the SVG ratio by raster rounding.
        expected = width * sheet_h / sheet_w
        assert abs(height - expected) <= 2, (
            f"{stem}.png is {width}x{height}, but {stem}.svg is {sheet_w:g}x{sheet_h:g}, which "
            f"rasterises to {width}x{expected:.0f}. The raster is of an older sheet. Run\n\n"
            f"{REGENERATE}"
        )


def _viewbox(svg: str) -> tuple[float, float]:
    """Read width and height from an SVG view box.

    Parameters
    ----------
    svg : str
        SVG document text.

    Returns
    -------
    tuple[float, float]
        View-box width and height.
    """
    head = svg.split(">", 2)[1]
    parts = head.split('viewBox="', 1)[1].split('"', 1)[0].replace(",", " ").split()
    return float(parts[2]), float(parts[3])


# Gallery asset inventory.


def test_the_gallery_holds_exactly_one_pair_per_example():
    """Provide one SVG and one PNG for every gallery example.

    Returns
    -------
    None
        Gallery assets match the generator's example inventory.
    """
    assert sorted(p.stem for p in GALLERY.glob("*.svg")) == SHEETS
    assert sorted(p.stem for p in GALLERY.glob("*.png")) == SHEETS


# Gallery-generator safeguards.


def test_the_generator_refuses_a_pandid_from_somewhere_else(tmp_path, monkeypatch):
    """Refuse to generate gallery assets with another installed package.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated replacement repository root.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to replace the generator root.

    Returns
    -------
    None
        The generator exits before importing another package installation.
    """
    monkeypatch.setattr(gallery, "ROOT", tmp_path)
    with pytest.raises(SystemExit, match="not this checkout"):
        gallery._pandid_is_this_checkout()


def test_the_generator_leaves_a_date_the_sheet_states_alone():
    """Preserve an explicit title-block date during gallery generation.

    Returns
    -------
    None
        An authored title-block date remains unchanged.
    """
    fs = Flowsheet("Stated Date")
    fs.title_block = TitleBlock(
        title="Stated Date",
        date="2026-03-04",
        revisions=[
            Revision("A", "2026-05-18", "Issued for internal review", "AA"),
            Revision("B", "2026-07-02", "Issued for design", "AA", "JS", "RL"),
        ],
    )
    gallery._stamp(fs)
    assert fs.title_block.date == "2026-03-04"
