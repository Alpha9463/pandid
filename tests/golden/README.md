# Golden SVG fixtures

One `.svg` per fixed scenario exercised by `tests/test_golden.py`: the six
examples' flowsheets (`01_ammonia_loop` .. `06_column_reflux`), where
`03_distillation_train` also covers `styling="pid"` with the stream table and
equipment-list / notes / legend furniture.

The flowsheets are rebuilt inline in `test_golden.py` rather than by running
`examples/*.py` directly — those scripts write into `examples/` (a side
effect a test suite shouldn't have) and `03`'s `TitleBlock` leaves `date`
empty, which `SvgRenderer` fills in with `datetime.now()`. The fixture sets
an explicit fixed date instead, per the "prefer a fixture over regexing it
out" rule for anything that varies run to run.

Comparisons run on *normalized* text (see `_normalize` in `test_golden.py`),
which canonicalizes `<defs>` ordering: `SvgRenderer._defs()` builds its
marker/symbol defs from Python `set`s (`used_colors`, `used_symbols`), so
their emitted order depends on the process's string-hash seed, not on
anything about the diagram — confirmed by rendering the same flowsheet under
several `PYTHONHASHSEED` values and diffing. Every other line compares
verbatim, so a real rendering regression still fails the test.

## Regenerating

After an intentional rendering change:

```
PFD_UPDATE_GOLDEN=1 python -m pytest tests/test_golden.py -q
```

Then inspect `git diff tests/golden/` before committing — a golden update
should have an obvious, explainable reason (a deliberate layout/styling
change), not just "the test was red."
