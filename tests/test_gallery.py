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

What is no longer re-run is :func:`gallery.render`, and only its own two lines:
the capture underneath it still runs over every example, since ``test_golden``'s
pass over the examples goes through that same :func:`gallery.flowsheet`, and
:func:`gallery._stamp` runs below. So a sheet regenerated through a broken
``to_svg`` or ``normalize`` is caught on the run after the regeneration rather
than on the one that broke it. That is the whole of what this trades away.

**Why the whole gallery, on every push.** Comparing every sheet is two file reads
apiece now, so neither cheaper design is worth the failure mode it brings.
Checking only the sheets whose example changed would have let this very drift
through, since the change that stales a sheet is often in ``pandid/`` rather
than in the example; and it needs a diff base, which a shallow CI clone does not
reliably have. Leaving it to a scheduled job means finding out after the merge.

**Why the SVG is compared exactly and the PNG is not.** The SVG is deterministic:
given the same code it is the same text, once ``<defs>`` ordering is canonicalised
and the provenance block -- which names a version, and so moves at every release
-- is dropped. Both rules are :func:`test_golden._normalize`, imported rather
than restated: comparing two files is worth only as much as the two sides having
been canonicalised by the same rule. A PNG is a raster, and its bytes come out of
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
def test_the_committed_sheet_is_the_drawing_its_golden_holds(stem, monkeypatch):
    """A gallery that has drifted shows a reader a drawing nobody can produce."""
    path = GALLERY / f"{stem}.svg"
    if not path.exists():
        pytest.fail(f"docs/gallery/{stem}.svg is missing. Run\n\n{REGENERATE}", pytrace=False)
    committed = _normalize(path.read_text(encoding="utf-8"))
    golden = _normalize((GOLDEN / f"{stem}.svg").read_text(encoding="utf-8"))
    if committed != golden:
        golden = _reconciled(stem, golden, monkeypatch)
    if committed != golden:
        pytest.fail(
            f"docs/gallery/{stem}.svg is not the drawing tests/golden/{stem}.svg holds.\n"
            f"The gallery is generated; regenerate it with\n\n{REGENERATE}\n"
            "and commit the result with the change that moved it. Neither file here is a "
            "render, so if tests/test_golden.py is failing as well, that is the one to read "
            f"first -- and if the line below is the title block's date, examples/{stem}.py has "
            "started stating one of its own: the fixture then has to state the same date, and "
            "the stem has to leave test_golden._DATE_LEFT_TO_THE_RENDERER, which is masking it "
            "there.\n\n" + _diff(committed, golden),
            pytrace=False,
        )


def _reconciled(stem: str, golden: str, monkeypatch: pytest.MonkeyPatch) -> str:
    """*golden*, re-dated where the two committed artefacts are entitled to differ.

    ``03`` and ``08`` leave ``TitleBlock.date`` blank for ``SvgRenderer`` to fill
    in with today's, which is a date no committed artefact can carry -- so both
    of them pin it, and they pin it differently: the fixture in
    ``test_golden.py`` to a constant, ``scripts/gallery.py`` to the newest
    revision's date, the date the sheet was in fact issued at. Neither is wrong
    and neither is drift; the example gives the two nothing to agree on. That
    one cell is swapped so the rest of the sheet can still be compared exactly.

    It is swapped only while the example really does leave the field blank, and
    that is *read off the example*, not assumed from a list of stems. The moment
    an example states a date of its own, the date becomes a field of the drawing
    like any other, the two artefacts do have something to agree on, and
    swapping the cell would retire the only check left on it -- which is how a
    value gets accepted, quietly replaced, and shipped. So the golden comes back
    untouched and the mismatch is reported, with the message above saying where
    the masking is.
    """
    stated, drawn = _dates_either_side_of_the_stamp(stem, monkeypatch)
    if stated:
        return golden
    pinned = SCENARIOS[stem][0]().title_block.date
    cell = f">{pinned}<"
    assert golden.count(cell) == 1, (
        f"tests/golden/{stem}.svg does not carry the fixture's date {pinned!r} in exactly one cell"
    )
    return golden.replace(cell, f">{drawn}<")


def _dates_either_side_of_the_stamp(stem: str, monkeypatch: pytest.MonkeyPatch) -> tuple[str, str]:
    """What ``examples/NN.py`` puts in the date cell, and what the gallery draws.

    :func:`gallery._stamp` fills a blank date and leaves a stated one alone, so
    by the time :func:`gallery.flowsheet` hands the flowsheet back the two cases
    are the same string and no longer tell apart -- which is the whole reason
    the field is read here on the way in, through a stand-in that records it and
    then defers to the real rule. Standing in for the length of one call is what
    :func:`gallery.flowsheet` itself does to ``Flowsheet.render``, and for the
    same reason: the value wanted is one nothing hands back.

    Neither date is restated here. The first is the example's own, and the
    second is whatever the generator's rule makes of it, so a change to either
    moves this with it.
    """
    stated: list[str] = []
    stamp = gallery._stamp

    def record(fs):
        stated.append(fs.title_block.date)
        stamp(fs)

    monkeypatch.setattr(gallery, "_stamp", record)
    fs, _ = gallery.flowsheet(stem)
    return stated[0], fs.title_block.date


def test_a_date_the_example_states_is_compared_and_not_swapped_away(monkeypatch):
    """The swap above is for a blank field, and only a blank field.

    Written because it was not: the first version of :func:`_reconciled` blanked
    the fixture's date and stamped it, which asserted what the example does
    rather than reading it. Given ``03`` an explicit date, the gallery drew that
    date, the golden was re-dated to it anyway, and a changed field of a real
    drawing passed -- while the render comparison this file used to make caught
    it. That is the failure this suite keeps finding: a value accepted, quietly
    replaced, and the sheet shipped.

    Two claims, and the first is what stops the second being vacuous: today's
    ``03`` leaves its date blank, so the golden really is re-dated; an ``03``
    that states its own is left alone, so the mismatch reaches the comparison.
    The stand-in is put where the example is, not where the reading is -- it
    builds the fixture's flowsheet, states a date on it and hands it to
    :func:`gallery._stamp` exactly as :func:`gallery.flowsheet` does, so what is
    being tested is still the reading.
    """
    stem = "03_distillation_train"
    golden = _normalize((GOLDEN / f"{stem}.svg").read_text(encoding="utf-8"))
    assert _reconciled(stem, golden, monkeypatch) != golden, (
        "03 leaves its date to the renderer today"
    )

    build, kwargs = SCENARIOS[stem]

    def states_its_own_date(name):
        fs = build()
        fs.title_block.date = "2099-12-31"
        gallery._stamp(fs)  # fills nothing: the field is not blank
        return fs, kwargs

    monkeypatch.setattr(gallery, "flowsheet", states_its_own_date)
    assert _reconciled(stem, golden, monkeypatch) == golden, (
        "a date the example states is a field of the drawing and has to be compared, not "
        "replaced with the one the gallery would have stamped"
    )


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
