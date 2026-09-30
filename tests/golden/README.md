# Golden SVG fixtures

These five fixtures provide exact-output coverage for distinct drawing modes:

- `02_manual_layout`: manual placement and debug overlay.
- `03_distillation_train`: furnished PFD.
- `11_ethanol_pid`: dense P&ID with controls and utilities.
- `12_block_flow_diagram`: automatic BFD layout.
- `18_fixed_bed_recycle`: automatic recycle layout with line numbers.

`tests/test_golden.py` compares each current render to its fixture. The gallery
documents runnable examples and is regenerated after output changes.

SVGs are normalized with `tests/_svg_compare.py` before comparison. The
normalizer sorts `<defs>` and removes renderer provenance so hash-seed and
version metadata do not change a fixture.

## Regenerating

After an example or rendering change, regenerate affected gallery assets and
the five goldens, then inspect both diffs:

```bash
python scripts/gallery.py
PANDID_UPDATE_GOLDEN=1 python -m pytest tests/test_golden.py -q
```
