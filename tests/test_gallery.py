"""``docs/gallery/``: the committed sheets, against the goldens of the same drawings.

The gallery is generated -- twenty-one examples rendered to SVG and rasterised to
PNG by ``scripts/gallery.py`` -- and until this file existed nothing held it to
its source. It drifted, and drifted invisibly: ``04_control_loop.svg`` sat on
``main`` through a dozen rendering PRs showing a sheet 526 px tall with an
instrument panel on it and no LT-101, which was a drawing the package had
stopped producing. Every one of those PRs was individually right to say "a
re-rasterise is coming"; what was missing was anything that noticed it had not.

That is the same gap ``_vendored_symbols.py`` had before #150 and ``docs/api.md``
had before #179, and this is the same answer: regenerate and compare.

**Why the golden and not a fresh render.** The sheet under ``docs/gallery/`` and
the one under ``tests/golden/`` are the same drawing out of the same example, so
re-rendering every example here asserted a third time what ``tests/test_golden.py``
already asserts twice: that ``examples/NN.py`` draws what is committed. #302
measured what the third copy cost -- rewording one SVG comment, a change that
moves no geometry at all, failed 64 tests, of which 43 carried all of the
information. So this compares the two *committed* artefacts to each other and
leaves the renderer to ``test_golden.py``, which renders every example already,
and does it twice: from its own fixture and from the example.

The two corpora are one corpus, which is what makes that sound:
``test_golden.test_every_example_has_a_fixture`` asserts its scenarios are
exactly :func:`gallery.sheets`, so every sheet here has a golden behind it and
every golden is held to the example that draws it. A stale gallery still fails
here -- against the drawing the example is known to draw, rather than against a
third render of it.

The two are compared without an exception of any kind, which took a change in
``test_golden.py`` to be able to say. ``03`` and ``08`` leave ``TitleBlock.date``
blank; the fixture used to pin it to a constant while ``scripts/gallery.py``
stamped the sheet's issue date, so the two committed artefacts stood one cell
apart for a reason that was about neither drawing, and this file had to hold a
rule for telling that cell from a real one. ``test_golden._pin_the_issue_date``
pins it the way the generator does instead, the two agree, and the rule is gone
rather than written more carefully.

What is no longer re-run is :func:`gallery.render`, and only its own two lines:
the capture underneath it still runs over every example, since ``test_golden``'s
pass over the examples goes through that same :func:`gallery.flowsheet`. So a
sheet regenerated through a broken ``to_svg`` or ``normalize`` is caught on the
run after the regeneration rather than on the one that broke it. That is the
whole of what this trades away.

**Why the whole gallery, on every push.** Comparing every sheet is two file reads
apiece now, so neither cheaper design is worth the failure mode it brings.
Checking only the sheets whose example changed would have let this very drift
through, since the change that stales a sheet is often in ``pandid/`` rather
than in the example; and it needs a diff base, which a shallow CI clone does not
reliably have. Leaving it to a scheduled job means finding out after the merge.

**Why the SVG is compared exactly and the PNG is not.** The SVG is deterministic:
given the same code it is the same text, once ``<defs>`` ordering is
canonicalised -- :func:`test_golden._normalize`'s rule, imported rather than
restated, since two files compared under two rules are not compared at all.
``_normalize`` also empties the provenance block, and that half is *undone*
here rather than inherited: see
:func:`_with_the_provenance_the_renderer_writes`, which puts back what this
version of the renderer writes, so a committed sheet still has to name the
version it was drawn by. A PNG is a raster, and its bytes come out of
whichever PDFium build and font substitution the machine that made it had, so
comparing them across a five-interpreter Linux matrix against a file made on one
developer's machine would be a flake and not a check. What is checked about the
raster is the part that is platform-independent and is exactly what goes stale
when a drawing changes shape: it exists, it is the width the gallery declares,
and it is the shape of the sheet beside it. A drawing that changed *within* the
same outline is caught by the SVG comparison, which fails first and sends the
author back to the one command that rewrites both.
"""

import importlib.util
import pathlib
import struct

import pytest

from pandid.render.svg import PROVENANCE_CLOSE, PROVENANCE_OPEN, _provenance

from test_golden import SCENARIOS, _normalize

ROOT = pathlib.Path(__file__).resolve().parent.parent
GALLERY = ROOT / "docs" / "gallery"
GOLDEN = ROOT / "tests" / "golden"
EXAMPLES = ROOT / "examples"


def _generator():
    """Import ``scripts/gallery.py`` by path.

    A dev-only script rather than part of the package, exactly as
    ``scripts/vendor_symbols.py`` and ``scripts/gen_devices.py`` are, and this is
    the loader ``tests/test_devices.py`` uses for those.
    """
    path = ROOT / "scripts" / "gallery.py"
    module_spec = importlib.util.spec_from_file_location("_pandid_script_gallery", path)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


gallery = _generator()
SHEETS = gallery.sheets()

REGENERATE = "    python scripts/gallery.py\n"


def _png_size(data: bytes) -> tuple[int, int]:
    """A PNG's pixel dimensions, out of its IHDR.

    Read from the header rather than through Pillow so this says the same thing
    on a machine without the optional ``[pdf]`` backend installed. The two
    32-bit big-endian words at offset 16 are the width and the height; that is
    the first chunk of every PNG, by the format's own rule.
    """
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssertionError("not a PNG")
    return struct.unpack(">II", data[16:24])


# ---------------------------------------------------------------------------
# The committed sheets, against the goldens of the same drawings
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("stem", SHEETS, ids=SHEETS)
def test_the_committed_sheet_is_the_drawing_its_golden_holds(stem):
    """A gallery that has drifted shows a reader a drawing nobody can produce."""
    path = GALLERY / f"{stem}.svg"
    if not path.exists():
        pytest.fail(f"docs/gallery/{stem}.svg is missing. Run\n\n{REGENERATE}", pytrace=False)
    committed = gallery.normalize(path.read_text(encoding="utf-8"))
    golden = _with_the_provenance_the_renderer_writes(
        _normalize((GOLDEN / f"{stem}.svg").read_text(encoding="utf-8")), SCENARIOS[stem][0]()
    )
    if committed != golden:
        pytest.fail(
            f"docs/gallery/{stem}.svg is not the drawing tests/golden/{stem}.svg holds.\n"
            f"The gallery is generated; regenerate it with\n\n{REGENERATE}\n"
            "and commit the result with the change that moved it. Neither file here is a "
            "render, so if tests/test_golden.py is failing as well, that is the one to read "
            "first.\n\n" + _diff(committed, golden),
            pytrace=False,
        )


def _with_the_provenance_the_renderer_writes(golden: str, fs) -> str:
    """*golden* with its emptied provenance block written back in.

    The two files reach this comparison in different states, and this is the
    line where that is dealt with rather than normalised away. A committed
    gallery sheet carries a full provenance block, version and all, because
    ``scripts/gallery.py`` writes what the renderer emitted. A golden does not:
    ``test_golden._normalize`` deletes the contents between the fences before the
    fixture is written out, so that cutting a release is not a diff of
    twenty-one fixtures -- ``test_a_version_bump_does_not_move_a_fixture`` is
    that rule, checked.

    Running ``_normalize`` over the gallery side as well would make the two
    agree, and would also stop anything at all looking at the version a
    committed sheet claims to have been drawn by. That is a real check: the
    gallery *does* have to be regenerated at a release, and before #302 this
    file was the only thing saying so. So the block is put back instead --
    :func:`~pandid.render.svg._provenance` is the renderer's own, called on the
    fixture whose golden this is, so what the committed sheet is held to is what
    this version of the renderer writes for this sheet, down to the ``dc:title``.
    """
    block = _provenance(fs)
    block = block[block.index(PROVENANCE_OPEN) :]
    lines = golden.split("\n")
    open_i, close_i = lines.index(PROVENANCE_OPEN), lines.index(PROVENANCE_CLOSE)
    return "\n".join(lines[:open_i] + block + lines[close_i + 1 :])


def _diff(committed: str, golden: str, context: int = 2) -> str:
    """First divergence with a little context -- not a 70 KB dump."""
    old, new = committed.split("\n"), golden.split("\n")
    total = max(len(old), len(new))
    row = next((i for i, (a, b) in enumerate(zip(old, new)) if a != b), min(len(old), len(new)))
    out = [f"first divergence at line {row + 1} of {total}:"]
    for k in range(max(0, row - context), min(total, row + context + 1)):
        mark = ">>" if k == row else "  "
        for label, lines in (("gallery", old), ("golden ", new)):
            out.append(f"{mark} [{k + 1}] {label}: {lines[k] if k < len(lines) else '<no line>'}")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# The rasters, against the sheets they were made from
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("stem", SHEETS, ids=SHEETS)
def test_the_raster_is_the_shape_of_its_sheet(stem):
    """The PNG is the SVG at :data:`gallery.WIDTH`, so it is that shape too.

    What a stale raster looks like: 04's sheet grew from 526 to 659 units tall
    while its PNG stayed the old shape. Aspect ratio catches that without
    rasterising anything, and without depending on how a particular PDFium build
    draws a glyph.
    """
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
    """The sheet's width and height in its own user units."""
    head = svg.split(">", 2)[1]
    parts = head.split('viewBox="', 1)[1].split('"', 1)[0].replace(",", " ").split()
    return float(parts[2]), float(parts[3])


# ---------------------------------------------------------------------------
# The gallery as a set: nothing missing, nothing left behind, nothing unlisted
# ---------------------------------------------------------------------------


def test_the_gallery_holds_exactly_one_pair_per_example():
    """An example added without its sheet, or a sheet left behind by one that was
    renamed or removed, is drift of the other kind: the directory and the
    examples saying different things about what the library draws."""
    assert sorted(p.stem for p in GALLERY.glob("*.svg")) == SHEETS
    assert sorted(p.stem for p in GALLERY.glob("*.png")) == SHEETS


def test_the_gallery_readme_shows_every_sheet():
    """A committed sheet nobody links to is a sheet nobody sees.

    ``docs/gallery/README.md`` is the page the drawings are read on, so a sheet
    is only in the gallery once that page shows its PNG and links its SVG.
    """
    readme = (GALLERY / "README.md").read_text(encoding="utf-8")
    missing = [
        f"{stem}.{ext}"
        for stem in SHEETS
        for ext in ("svg", "png")
        if f"{stem}.{ext}" not in readme
    ]
    assert not missing, (
        "docs/gallery/README.md does not show " + ", ".join(missing) + ". Add a section for it."
    )


def test_the_readme_states_the_width_the_rasters_are_made_at():
    """The page tells the reader what it is showing them, so the number in it has
    to be the number the generator used."""
    readme = (GALLERY / "README.md").read_text(encoding="utf-8")
    assert f"{gallery.WIDTH} px" in readme


# ---------------------------------------------------------------------------
# The draw.io export an example writes beside its sheet
# ---------------------------------------------------------------------------


def _exporters():
    """The examples that write a ``.drawio`` as well as their sheet."""
    return [
        stem
        for stem in SHEETS
        if ".drawio" in (EXAMPLES / f"{stem}.py").read_text(encoding="utf-8")
    ]


def test_an_example_shows_the_drawio_export():
    """``fs.render("sheet.drawio")`` is a one-liner, and until now it appeared in
    ``README.md``, in ``docs/api.md`` and in ``scripts/drawio_samples.py`` and in
    no example at all — so the export was documented everywhere except the place
    a reader goes to see a call being made. This is what notices when the line is
    deleted rather than moved."""
    assert _exporters(), (
        "no example writes a .drawio. The export is one line and examples/ is where "
        "a reader looks for one; put the call back beside a sheet's own render()."
    )


@pytest.mark.parametrize("stem", _exporters(), ids=_exporters())
def test_the_export_is_not_counted_as_a_second_sheet(stem):
    """:func:`gallery.flowsheet` refuses an example that draws two sheets, and an
    example that exports calls ``render()`` twice. What the second call writes is
    the same drawing in a second format, so it is passed over and the count goes
    on meaning what it says for a file that really does draw two.

    :func:`gallery.flowsheet` raising ``SystemExit`` is the check. The assertion
    after it is not, and the one it replaced was not either: the module fixture
    this test used to take was satisfied by any non-empty string, as ``fs.units``
    is by any non-empty flowsheet. What is asserted is that the call *returns* --
    which it only does if the ``.drawio`` write was passed over. It builds the
    flowsheet and stops there; nothing in this file renders one."""
    source = (EXAMPLES / f"{stem}.py").read_text(encoding="utf-8")
    assert source.count(".render(") >= 2, "an exporting example writes its sheet as well"
    fs, _ = gallery.flowsheet(stem)
    assert fs.units, "and the generator still gets the example's own flowsheet out of it"


# ---------------------------------------------------------------------------
# The trap the generator is built around
# ---------------------------------------------------------------------------


def test_the_generator_refuses_a_pandid_from_somewhere_else(tmp_path, monkeypatch):
    """The failure this whole file would otherwise be blind to.

    ``examples/_bootstrap.py`` prepends the repo root only when ``pandid`` is not
    already importable, so on a machine with a released ``pandid`` installed the
    examples render against *that*. A gallery generated that way shows the last
    release and a check run against it passes on the wrong code -- the one
    failure mode in which everything here still goes green.
    """
    monkeypatch.setattr(gallery, "ROOT", tmp_path)
    with pytest.raises(SystemExit, match="not this checkout"):
        gallery._pandid_is_this_checkout()
