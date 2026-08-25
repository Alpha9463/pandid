"""``docs/gallery/``: the committed sheets, against the examples they came from.

The gallery is generated -- twenty-one examples rendered to SVG and rasterised to
PNG by ``scripts/gallery.py`` -- and until this file existed nothing held it to
its source. It drifted, and drifted invisibly: ``04_control_loop.svg`` sat on
``main`` through a dozen rendering PRs showing a sheet 526 px tall with an
instrument panel on it and no LT-101, which was a drawing the package had
stopped producing. Every one of those PRs was individually right to say "a
re-rasterise is coming"; what was missing was anything that noticed it had not.

That is the same gap ``_vendored_symbols.py`` had before #150 and ``docs/api.md``
had before #179, and this is the same answer: regenerate and compare.

**Why the whole gallery, on every push.** Rendering all twenty-one sheets costs
about 5 s, four fifths of it example 11 and most of the rest example 14 --
measured, not assumed. That is small
enough that the two cheaper designs both cost more than they save. Checking only
the sheets whose example changed would have let this very drift through, since
the change that stales a sheet is often in ``pandid/`` rather than in the
example; and it needs a diff base, which a shallow CI clone does not reliably
have. Leaving it to a scheduled job means finding out after the merge.

**Why the SVG is compared exactly and the PNG is not.** The SVG is deterministic:
given the same code it is the same text, once ``<defs>`` ordering is
canonicalised (:func:`gallery.normalize`, the rule ``tests/test_golden.py``
applies for the same reason). A PNG is a raster, and its bytes come out of
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

from pandid import Flowsheet
from pandid.document import Revision, TitleBlock

ROOT = pathlib.Path(__file__).resolve().parent.parent
GALLERY = ROOT / "docs" / "gallery"
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


@pytest.fixture(scope="module")
def rendered():
    """Every example rendered once, keyed by sheet name.

    Module-scoped because the corpus is the expensive part of this file and
    every test below wants all of it: rendered per-test it would be twenty
    renders a test rather than twenty in total.
    """
    return {stem: gallery.render(stem) for stem in SHEETS}


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
# The committed sheets, against a fresh render of the examples
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("stem", SHEETS, ids=SHEETS)
def test_the_committed_sheet_is_what_the_example_draws_today(rendered, stem):
    """A gallery that has drifted shows a reader a drawing nobody can produce."""
    path = GALLERY / f"{stem}.svg"
    if not path.exists():
        pytest.fail(f"docs/gallery/{stem}.svg is missing. Run\n\n{REGENERATE}", pytrace=False)
    committed = gallery.normalize(path.read_text(encoding="utf-8"))
    fresh = rendered[stem]
    if committed != fresh:
        pytest.fail(
            f"docs/gallery/{stem}.svg is not what examples/{stem}.py draws today.\n"
            f"The gallery is generated; regenerate it with\n\n{REGENERATE}\n"
            "and commit the result with the change that moved it.\n\n" + _diff(committed, fresh),
            pytrace=False,
        )


def _diff(committed: str, fresh: str, context: int = 2) -> str:
    """First divergence with a little context -- not a 70 KB dump."""
    old, new = committed.split("\n"), fresh.split("\n")
    total = max(len(old), len(new))
    row = next((i for i, (a, b) in enumerate(zip(old, new)) if a != b), min(len(old), len(new)))
    out = [f"first divergence at line {row + 1} of {total}:"]
    for k in range(max(0, row - context), min(total, row + context + 1)):
        mark = ">>" if k == row else "  "
        for label, lines in (("committed", old), ("rendered ", new)):
            out.append(f"{mark} [{k + 1}] {label}: {lines[k] if k < len(lines) else '<no line>'}")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# What an example prints about itself, against what its sheet reports
# ---------------------------------------------------------------------------
# Seven examples end in
#
#     for issue in fs.validate():
#         print(f"  {issue}")
#
# and an example is the thing a reader copies. Those seven used to call
# `validate()` without the `diagram=` their own `render()` was given, so a
# sheet drawn as a P&ID printed `stream-table-missing` -- a finding made
# under ISO 10628-1 4.3.2 d), which is a process flow diagram's clause and
# not that sheet's -- while `scripts/gallery.py`, rendering the very same
# flowsheet, reported nothing.
#
# The mechanical cure was to spell `diagram=` out a second time in every
# example, and having to keep two calls in step **was the bug**: the same
# argument written twice is what drifted. `validate()` reads the last
# render instead, and this is what holds it there -- across the whole
# corpus rather than across the seven that happen to print today, so an
# example that takes the print up later is covered before it is written.


@pytest.fixture(scope="module")
def checked():
    """Every example built, drawn as it draws itself, and kept.

    :func:`gallery.render` throws the flowsheet away and keeps the SVG;
    these tests want the opposite. Module-scoped for the reason `rendered`
    is: the renders are the cost, and every test below wants all of them.
    """
    out = {}
    for stem in SHEETS:
        fs, kwargs = gallery.flowsheet(stem)
        fs.to_svg(**kwargs)
        out[stem] = (fs, kwargs)
    return out


@pytest.mark.parametrize("stem", SHEETS, ids=SHEETS)
def test_what_an_example_prints_is_what_its_own_sheet_reports(checked, stem):
    """Two halves of one statement, and the second is the one that bites.

    **The bare call is the diagram-aware call.** Whatever the example
    passed to `render()`, a `validate()` that names nothing answers about
    that drawing, so the two can no longer be written apart.

    **And what it prints is genuinely on the sheet.** `fs.warnings` is
    what the render itself found, so a finding printed but not on that
    list is a finding about some other drawing -- which is exactly what
    the five P&ID examples used to print. The converse is allowed and is
    not drift: `crossing-unmarked` and the title-block fit codes are the
    *renderer's* findings, made from options the validator is never
    handed, so the sheet may report what a bare `validate()` cannot.
    """
    fs, kwargs = checked[stem]
    printed = [str(i) for i in fs.validate()]
    assert printed == [str(i) for i in fs.validate(diagram=kwargs.get("diagram"))]

    reported = [str(w) for w in fs.warnings]
    assert [f for f in printed if f not in reported] == []


def test_the_corpus_still_holds_a_sheet_the_diagram_changes_the_answer_for(checked):
    """Keeps the test above from passing because there is nothing to catch.

    Every assertion in it is trivially true on a corpus of nothing but
    PFDs, and the corpus was one sheet away from that: `12` was the last
    example to raise `stream-table-missing`, and declaring it a BFD is what
    stopped it. So this pins that at least one shipped sheet still reports
    something different from what the same model reports as a plain PFD.
    """
    moved = [
        stem
        for stem, (fs, _) in checked.items()
        if [str(i) for i in fs.validate()] != [str(i) for i in fs.validate(diagram="pfd")]
    ]
    assert moved, "no shipped example is validated as anything but a PFD"


#: What the shipped corpus reports: every finding on ``fs.warnings`` after
#: an example draws itself, per sheet, sorted. A stem absent from this
#: table reports nothing at all, which is the state fourteen of the
#: twenty-one are in.
#:
#: Written down because until it was, nothing noticed a finding arriving
#: on a reference sheet or leaving one. ``12_block_flow_diagram`` was the
#: last example to raise ``stream-table-missing``, made under ISO
#: 10628-1 4.3.2 d) -- a *process flow diagram*'s clause, on a sheet that
#: is a block flow diagram and answers 4.2. The
#: examples are the documentation, and a finding nobody is holding to a
#: number is one that accumulates silently until the check stops meaning
#: anything.
#:
#: So this is meant to be edited, and only ever deliberately: a validator
#: change that moves what a shipped sheet reports has to say which sheet
#: and why, in the same commit that moves it.
#: Empty, and every one of the twenty-one sheets is in it. The seven
#: entries this table used to carry -- six ``lines-crowded`` and
#: ``nozzles-crowded`` between them, and one ``crossing-unmarked`` --
#: were every one of them a consequence of #502 drawing a material run
#: at twice the equipment it enters. All three floors are derived from
#: that rung: 5.3.2's clearance is twice the wider of two runs,
#: ``MIN_HEAD_CLEARANCE`` is twice the rung, and ``HOP_R`` is the hop's
#: clearance plus a pen. Restoring the run to the weight of the
#: equipment (pandid/render/weights.py) moved all three back under the
#: room the sheets already had, and the corpus came out clean.
#:
#: That is the whole of #498, which 0.1.4 shipped as a known issue: the
#: nine clearances it names are not crowded once the pen that crowded
#: them is the one a drawing office rules.
CORPUS_FINDINGS: "dict[str, list[str]]" = {}


@pytest.mark.parametrize("stem", SHEETS, ids=SHEETS)
def test_the_sheet_reports_what_the_corpus_says_it_reports(checked, stem):
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
    """A stem that has been renamed or retired must not leave an entry
    behind that no test can ever reach."""
    assert set(CORPUS_FINDINGS) <= set(SHEETS)


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
def test_the_export_is_not_counted_as_a_second_sheet(rendered, stem):
    """:func:`gallery.flowsheet` refuses an example that draws two sheets, and an
    example that exports calls ``render()`` twice. What the second call writes is
    the same drawing in a second format, so it is passed over and the count goes
    on meaning what it says for a file that really does draw two.

    The ``rendered`` fixture is the check: it runs ``flowsheet(stem)``, which
    raises ``SystemExit`` if the ``.drawio`` write is counted as a sheet."""
    source = (EXAMPLES / f"{stem}.py").read_text(encoding="utf-8")
    assert source.count(".render(") >= 2, "an exporting example writes its sheet as well"
    assert rendered[stem], "and the generator still gets exactly one sheet out of it"


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


def test_the_generator_leaves_a_date_the_sheet_states_alone():
    """``_stamp`` fills a *blank* date cell. It must never replace a stated one.

    The substitution exists because ``03`` and ``08`` state no date, and a sheet
    committed to a repository cannot carry ``datetime.now()``. Widened by one
    clause -- ``if tb.revisions`` where it now reads ``if not tb.date and
    tb.revisions`` -- it stops filling a gap and starts overwriting the author,
    and the drawing ships dated a day nobody typed. #482 made exactly that
    mutation, and it was review rather than a test that caught it. #467, #370
    and #294 are the same shape.

    Asked directly rather than left to the corpus, because the corpus barely
    covers it: made unconditional, ``_stamp`` is caught by exactly one of the
    twenty-one sheets -- and only because ``11_ethanol_pid`` happens to be dated
    five days after its last revision. The other ten that state a date state
    their newest revision's, so an overwrite is invisible on them. The date here
    is therefore deliberately *not* the newest revision's, which is what makes
    this non-vacuous: an overwriting ``_stamp`` has to move it.
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
