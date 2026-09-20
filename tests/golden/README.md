# Golden SVG fixtures

One `.svg` per fixed scenario exercised by `tests/test_golden.py`, one scenario
per example. `03_distillation_train`, `08_from_data`, `09_line_numbers`,
`10_ethanol_pfd` and `11_ethanol_pid` cover `border="zone"` with the
equipment-list / notes / legend furniture, and a stream table on all but `11`.
`08_from_data` is built through `Flowsheet.from_dict`, so it also pins the
declarative spec format's rendered output, and `09_line_numbers` pins a sheet
whose lines are identified by line number rather than stream number.

`10_ethanol_pfd` and `11_ethanol_pid` are the two flagship sheets and the two
drawn at a fixed `page_size="A3"`, so they are what pins the page fit as well as
the drawing. Between them they carry the widest coverage in the corpus: valve
stations, five control loops, a repeated interlock square, utility headers, a
conveyor, off-page connectors, a utilities summary and a sectioned stream table.
`11` is the densest sheet in the repo, so its fixture is the largest here and
will move whenever the sheet improves; that is the price of pinning what the
README points at.

`02_manual_layout` is the one fixture drawn with the coordinate overlay on
(`debug=True`), matching the example it comes from. It is therefore what pins
the overlay: the grid, the coordinates written on it, the anchor markers and the
port markers all land in that file, so a change to any of them shows up as a
drawing rather than as an arithmetic claim. Every other fixture draws with it
off, which is what holds the rest of the corpus to being byte for byte what it
was before the feature existed.

`14_tank_farm` is the tank farm, the third sheet drawn at `page_size="A3"` and
the one that pins the storage, containment and line-fitting families: a floating
roof, a fixed roof and a sphere, a conservation vent with its flame arrestor, a
detonation-rated arrestor in the vapour return, a spectacle blind, a compensator,
both strainer bodies and the eccentric/concentric reducer pair around one pump.
It is also the only scenario whose loop numbers are *allocated* rather than
typed, so it is what holds `add_loop`'s counter to a drawing rather than to an
arithmetic claim in a unit test.

`12_block_flow_diagram` is the block flow diagram, the one scenario a level
above the PFD and the only one with process connections on the north and south
faces. It is also the only sheet whose boxes size *themselves*: nothing in it
carries a `width` or a `height`, so it is what turns the nozzle pitch, the
minimum box and the label allowance into a drawing that can be looked at rather
than an arithmetic claim in a unit test.

`13_mineral_dewatering` is the solids circuit, and the only fixture that draws a
dryer, a furnace, a blower or a funnel at all. It is also the only one with a
`Tee(branch="inlet")` — a junction where a second stream *joins* a run rather
than leaving it — and the only one whose stream table is wider than the drawing
above it, so it is what pins a sheet sized to fit furniture the diagram does not
set the width of. Its title block states its own date, so it needs no pinning.

`17_stirred_reactor_train`, `18_fixed_bed_recycle` and `20_molecular_sieve_dryer`
are what pin the **composition layer** as drawings. `17` is the only fixture with
a group-28 agitator, its drive motor or a jacketed body on it; `18` and `20` draw
ISO item 27.8's packed bed in a reactor and in a pair of adsorbers, which is the
same mark twice and is exactly the claim `docs/api.md` makes in prose. `18` also
holds `internals=` to leaving the default agitator out — a stirrer appearing
through the catalyst would move that fixture and nothing else. `19_absorber_stripper`
puts two group-27 internals on one sheet, a valve deck and a packed bed, so a
change that stopped telling two towers apart shows up as a drawing.

`17` is the fourth fixture on a fixed `page_size="A3"`, `18` the third laid out
end to end with no `pin()` on it and the first of those to carry line numbers,
and `20` the only one with a repeated *logic* square — eight of them, one at each
valve one sequence strokes. All four state their own title-block dates, so none
of them is pinned.

`21_alumina_refinery` is the Bayer circuit and the largest fixture here:
twenty-eight tagged items, fifty-six streams and a sheet sized to its own
drawing rather than to a page. It is the only scenario drawing a crusher, a
mill, a hydrocyclone, a thickener, an evaporator or a calciner; the
only one with two cake-forming filters piping `wash_in` and `cake` as well as
the filtrate; and the only one whose process returns to its own first unit, so
it is what holds a closed circuit — and a stream table wider than any standard
page — to a drawing rather than to an arithmetic claim. It states its own
title-block date, so nothing here is pinned.

The flowsheets come directly from `examples/*.py`, captured through
`scripts/gallery.py` without writing output files. The capture preserves render
options and stamps blank title-block dates from the latest revision.
`tests/_render_cases.py` supplies fresh example models to the geometry tests.

`test_golden_svg` compares each fresh example render against its golden once.
The gallery tests compare the committed `docs/gallery/*.svg` files against these
same goldens, and separately check PNG dimensions, completeness and README links.

Comparisons run on *normalized* text (see `normalize` in `tests/_svg_compare.py`),
which canonicalizes two things and leaves every other line to compare verbatim,
so a real rendering regression still fails the test.

**`<defs>` ordering.** `SvgRenderer._defs()` builds its marker/symbol defs from
Python `set`s (`used_colors`, `used_symbols`), so their emitted order depends on
the process's string-hash seed, not on anything about the diagram — confirmed by
rendering the same flowsheet under several `PYTHONHASHSEED` values and diffing.

**The provenance block.** Every rendered sheet says what drew it, version
included. Left alone, bumping `pandid.__version__` would rewrite all twenty-one
fixtures for a reason that is about none of the drawings, and cutting a release
would be a diff of every artefact in the repository. The renderer therefore
fences the block between `<!-- pandid:provenance -->` and
`<!-- /pandid:provenance -->`, and `normalize` drops what lies between them — a
slice between two known lines, not a version pattern hunted across the document.
That is why the committed fixtures show the two fence comments with nothing in
between: they are stored normalized, so `git grep` finds no version number here.
The `<title>` above the fence is *not* dropped; it carries the sheet's own name
and no version, so it compares like any other line.
`test_a_version_bump_does_not_move_a_fixture` holds all of that to being true.

## Regenerating

After an intentional rendering change:

```
PANDID_UPDATE_GOLDEN=1 python -m pytest tests/test_golden.py -q
```

Then inspect `git diff tests/golden/` before committing: a golden update
should have an obvious, explainable reason (a deliberate layout/styling
change), not just "the test was red."
