"""Validate generated gallery assets and gallery-generator safeguards."""

import pathlib
import struct

import pytest

from _render_cases import copy_settled_case, gallery
from _svg_compare import normalize
from pandid import Flowsheet
from pandid.document import Revision, TitleBlock

ROOT = pathlib.Path(__file__).resolve().parent.parent
GALLERY = ROOT / "docs" / "gallery"


SHEETS = gallery.sheets()
DIAGRAM_VALIDATION_CASES = (
    "03_distillation_train",
    "11_ethanol_pid",
    "12_block_flow_diagram",
)

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


def _diff(expected: str, actual: str, context: int = 2) -> str:
    """Describe the first difference between two normalized SVG strings.

    Parameters
    ----------
    expected : str
        Expected normalized SVG.
    actual : str
        Actual normalized SVG.
    context : int, default=2
        Number of surrounding lines to include.

    Returns
    -------
    str
        Concise difference description.
    """
    old, new = expected.split("\n"), actual.split("\n")
    total = max(len(old), len(new))
    row = next((i for i, (a, b) in enumerate(zip(old, new)) if a != b), min(len(old), len(new)))
    out = [f"first divergence at line {row + 1} of {total}:"]
    for k in range(max(0, row - context), min(total, row + context + 1)):
        mark = ">>" if k == row else "  "
        for label, lines in (("expected", old), ("actual  ", new)):
            out.append(f"{mark} [{k + 1}] {label}: {lines[k] if k < len(lines) else '<no line>'}")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Rendered validation findings


@pytest.fixture(scope="module")
def checked(settled_gallery):
    """Render independent gallery copies and retain their validation state.

    Parameters
    ----------
    settled_gallery : dict[str, tuple[Flowsheet, dict]]
        Session-scoped routed source sheets.

    Returns
    -------
    dict[str, tuple[Flowsheet, dict, str]]
        Rendered sheets, options, and normalized SVGs keyed by example name.
    """
    out = {}
    for stem in SHEETS:
        fs, kwargs = copy_settled_case(settled_gallery, stem)
        out[stem] = (fs, kwargs, normalize(fs.to_svg(**kwargs)))
    return out


@pytest.mark.parametrize("stem", SHEETS, ids=SHEETS)
def test_current_render_matches_the_committed_gallery(checked, stem):
    """Match each example's current render to its committed gallery SVG."""
    _fs, _kwargs, actual = checked[stem]
    path = GALLERY / f"{stem}.svg"
    if not path.exists():
        pytest.fail(f"docs/gallery/{stem}.svg is missing. Run\n\n{REGENERATE}", pytrace=False)
    expected = normalize(path.read_text(encoding="utf-8"))
    if actual != expected:
        pytest.fail(
            f"docs/gallery/{stem}.svg no longer matches its example. Regenerate it with\n\n"
            f"{REGENERATE}\n" + _diff(expected, actual),
            pytrace=False,
        )


@pytest.mark.parametrize("stem", DIAGRAM_VALIDATION_CASES, ids=DIAGRAM_VALIDATION_CASES)
def test_what_an_example_prints_is_what_its_own_sheet_reports(checked, stem):
    """Match a bare validation call to the example's rendered diagram."""
    fs, kwargs, _svg = checked[stem]
    printed = [str(i) for i in fs.validate()]
    assert printed == [str(i) for i in fs.validate(diagram=kwargs.get("diagram"))]

    reported = [str(w) for w in fs.warnings]
    assert [f for f in printed if f not in reported] == []


@pytest.mark.parametrize("stem", SHEETS, ids=SHEETS)
def test_gallery_examples_render_without_warnings(checked, stem):
    """Keep every committed gallery example free from render warnings."""
    fs, _kwargs, _svg = checked[stem]
    assert not fs.warnings, f"{stem}: {[str(warning) for warning in fs.warnings]}"


# ---------------------------------------------------------------------------
# Committed gallery PNGs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("stem", SHEETS, ids=SHEETS)
def test_the_raster_is_the_shape_of_its_sheet(stem):
    """Match each gallery PNG dimensions to its SVG view box."""
    png = GALLERY / f"{stem}.png"
    if not png.exists():
        pytest.fail(f"docs/gallery/{stem}.png is missing. Run\n\n{REGENERATE}", pytrace=False)
    width, height = _png_size(png.read_bytes())
    assert width == gallery.WIDTH, (
        f"{stem}.png is {width} px wide, not the gallery's {gallery.WIDTH}. Run\n\n{REGENERATE}"
    )

    svg = (GALLERY / f"{stem}.svg").read_text(encoding="utf-8")
    sheet_w, sheet_h = _viewbox(svg)
    # The rasteriser rounds a fractional pixel up, so the height it lands on is
    # the exact ratio or the next pixel above it; two is that with room to spare
    # and is still far tighter than any change of shape a redrawn sheet makes.
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


# ---------------------------------------------------------------------------
# Gallery file inventory
# ---------------------------------------------------------------------------


def test_the_gallery_holds_exactly_one_pair_per_example():
    """Provide one SVG and one PNG for every gallery example."""
    assert sorted(p.stem for p in GALLERY.glob("*.svg")) == SHEETS
    assert sorted(p.stem for p in GALLERY.glob("*.png")) == SHEETS


# ---------------------------------------------------------------------------
# Gallery-generator safeguards
# ---------------------------------------------------------------------------


def test_the_generator_refuses_a_pandid_from_somewhere_else(tmp_path, monkeypatch):
    """Refuse to generate gallery assets with another installed package."""
    monkeypatch.setattr(gallery, "ROOT", tmp_path)
    with pytest.raises(SystemExit, match="not this checkout"):
        gallery._pandid_is_this_checkout()


def test_the_generator_leaves_a_date_the_sheet_states_alone():
    """Preserve an explicit title-block date during gallery generation."""
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
