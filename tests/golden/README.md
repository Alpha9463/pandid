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

The flowsheets are rebuilt inline in `test_golden.py` rather than by running
`examples/*.py` directly: those scripts write into `examples/` (a side
effect a test suite shouldn't have) and `03`'s and `08`'s `TitleBlock`s leave
`date` empty, which `SvgRenderer` fills in with `datetime.now()`. The fixture
sets an explicit fixed date instead, per the "prefer a fixture over regexing
it out" rule for anything that varies run to run. `10` and `11` state their own
dates, so those two need no pinning.

Comparisons run on *normalized* text (see `_normalize` in `test_golden.py`),
which canonicalizes `<defs>` ordering: `SvgRenderer._defs()` builds its
marker/symbol defs from Python `set`s (`used_colors`, `used_symbols`), so
their emitted order depends on the process's string-hash seed, not on
anything about the diagram, confirmed by rendering the same flowsheet under
several `PYTHONHASHSEED` values and diffing. Every other line compares
verbatim, so a real rendering regression still fails the test.

## Regenerating

After an intentional rendering change:

```
PANDID_UPDATE_GOLDEN=1 python -m pytest tests/test_golden.py -q
```

Then inspect `git diff tests/golden/` before committing: a golden update
should have an obvious, explainable reason (a deliberate layout/styling
change), not just "the test was red."
