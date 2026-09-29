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
GOLDEN = ROOT / "tests" / "golden"
EXAMPLES = ROOT / "examples"


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


# ---------------------------------------------------------------------------
# Committed gallery SVGs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("stem", SHEETS, ids=SHEETS)
def test_the_committed_sheet_matches_its_golden(stem):
    """Keep each committed gallery SVG aligned with its golden fixture."""
    path = GALLERY / f"{stem}.svg"
    if not path.exists():
        pytest.fail(f"docs/gallery/{stem}.svg is missing. Run\n\n{REGENERATE}", pytrace=False)
    committed = normalize(path.read_text(encoding="utf-8"))
    golden = normalize((GOLDEN / f"{stem}.svg").read_text(encoding="utf-8"))
    if committed != golden:
        pytest.fail(
            f"docs/gallery/{stem}.svg does not match tests/golden/{stem}.svg.\n"
            f"The gallery is generated; regenerate it with\n\n{REGENERATE}\n"
            "and commit the result with the change that moved it.\n\n" + _diff(committed, golden),
            pytrace=False,
        )


def _diff(committed: str, golden: str, context: int = 2) -> str:
    """Describe the first difference between two normalized SVG strings.

    Parameters
    ----------
    committed : str
        Committed gallery SVG.
    golden : str
        Expected golden SVG.
    context : int, default=2
        Number of surrounding lines to include.

    Returns
    -------
    str
        Concise difference description.
    """
    old, new = committed.split("\n"), golden.split("\n")
    total = max(len(old), len(new))
    row = next((i for i, (a, b) in enumerate(zip(old, new)) if a != b), min(len(old), len(new)))
    out = [f"first divergence at line {row + 1} of {total}:"]
    for k in range(max(0, row - context), min(total, row + context + 1)):
        mark = ">>" if k == row else "  "
        for label, lines in (("committed", old), ("golden   ", new)):
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
    dict[str, tuple[Flowsheet, dict]]
        Rendered sheets and their render options keyed by example name.
    """
    out = {}
    for stem in SHEETS:
        fs, kwargs = copy_settled_case(settled_gallery, stem)
        fs.to_svg(**kwargs)
        out[stem] = (fs, kwargs)
    return out


@pytest.mark.parametrize("stem", SHEETS, ids=SHEETS)
def test_what_an_example_prints_is_what_its_own_sheet_reports(checked, stem):
    """Match a bare validation call to the example's rendered diagram."""
    fs, kwargs = checked[stem]
    printed = [str(i) for i in fs.validate()]
    assert printed == [str(i) for i in fs.validate(diagram=kwargs.get("diagram"))]

    reported = [str(w) for w in fs.warnings]
    assert [f for f in printed if f not in reported] == []


def test_the_corpus_still_holds_a_sheet_the_diagram_changes_the_answer_for(checked):
    """Keep at least one non-PFD example in the gallery corpus."""
    moved = [
        stem
        for stem, (fs, _) in checked.items()
        if [str(i) for i in fs.validate()] != [str(i) for i in fs.validate(diagram="pfd")]
    ]
    assert moved, "no shipped example is validated as anything but a PFD"


# Expected validation codes after each gallery example is rendered.
# An omitted example is expected to render without warnings.
CORPUS_FINDINGS: "dict[str, list[str]]" = {}


@pytest.mark.parametrize("stem", SHEETS, ids=SHEETS)
def test_the_sheet_reports_what_the_corpus_says_it_reports(checked, stem):
    """Match each rendered gallery sheet to its expected warning codes."""
    fs, _ = checked[stem]
    found = sorted(w.code for w in fs.warnings)
    expected = sorted(CORPUS_FINDINGS.get(stem, []))
    if found != expected:
        pytest.fail(
            f"examples/{stem}.py now reports {found}, and CORPUS_FINDINGS says "
            f"{expected}.\n"
            f"If the change is intended, edit CORPUS_FINDINGS in "
            f"this file in the same commit and say per sheet what moved and "
            f"why. If it is not, the validator change that moved it is "
            f"reporting something new about a reference drawing.",
            pytrace=False,
        )


def test_the_corpus_table_names_no_sheet_the_gallery_does_not_have():
    """Keep warning expectations limited to current gallery examples."""
    assert set(CORPUS_FINDINGS) <= set(SHEETS)


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
# Draw.io example exports
# ---------------------------------------------------------------------------


def _exporters():
    """Find examples that write a Draw.io file.

    Returns
    -------
    list[str]
        Example filename stems containing a ``.drawio`` render call.
    """
    return [
        stem
        for stem in SHEETS
        if ".drawio" in (EXAMPLES / f"{stem}.py").read_text(encoding="utf-8")
    ]


def test_an_example_shows_the_drawio_export():
    """Keep at least one Draw.io export in the example corpus."""
    assert _exporters(), (
        "no example writes a .drawio. The export is one line and examples/ is where "
        "a reader looks for one; put the call back beside a sheet's own render()."
    )


@pytest.mark.parametrize("stem", _exporters(), ids=_exporters())
def test_the_export_is_not_counted_as_a_second_sheet(stem):
    """Capture the SVG sheet when an example also exports Draw.io."""
    source = (EXAMPLES / f"{stem}.py").read_text(encoding="utf-8")
    assert source.count(".render(") >= 2, "an exporting example writes its sheet as well"
    fs, _kwargs = gallery.flowsheet(stem)
    assert isinstance(fs, Flowsheet)


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
