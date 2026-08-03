#!/usr/bin/env python3
"""Generate drawio-samples/: the exported ``.drawio`` files a reader opens.

Run:  python scripts/drawio_samples.py

`scripts/gallery.py` exists because the committed SVGs had nothing holding them
to their source and drifted: `04_control_loop.svg` sat on `main` for a dozen
rendering PRs showing a drawing the package had stopped producing. The
`.drawio` samples were being made by hand -- the command was written into a
commit message and nowhere else -- which is that same hazard with none of the
guard, and it had already bitten: three of the four committed samples were
pre-#236 exports carrying defects the branch had fixed, and the file the author
opened to review the exporter was one of them.

So this is the one command that rebuilds them, and `tests/test_drawio.py` is
what fails when a committed sample is not what the exporter emits.

**The samples are a subset, not the gallery.** The gallery is every example
because a reader browses it; these are opened one at a time in a draw.io window
to check the exporter, and a fifth or a tenth of them tells nobody anything a
fourth did not. :data:`SAMPLES` is the four, and what each is there to show is
written against it.

Everything about *how* an example is caught and stamped is `gallery.py`'s and
is imported rather than repeated: `flowsheet()` imports the example with
`Flowsheet.render` stubbed so the one call at the end of it hands over the
flowsheet and the options it was about to be drawn with, and `_stamp` fills a
blank title-block date from the newest revision so a regenerated file does not
differ from itself tomorrow.
"""

import argparse
import importlib.util
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

SAMPLES = {
    # The exporter's hard case and the one the author reviews: a fixed page, a
    # zone-ruled border, a title strip with a revision history, a legend, an
    # equipment list, a notes box, twenty instrument taps, pneumatic hatching
    # and sixteen line numbers to place.
    "11_ethanol_pid": "a full P&ID on A3 paper, with every piece of furniture",
    # A zone-ruled sheet with no page size: the frame is grown around the
    # drawing rather than fixed by the paper, so the drawing keeps its own
    # coordinates and the furniture docks to the grown frame. It is also the
    # only sample that carries a stream table -- 21 stream columns and a section
    # heading spanning all of them -- which is why its example writes its own
    # .drawio beside its sheet, as `11` does: the line an example makes writes
    # the file the repository already shows. It is also a PFD,
    # which draws the arrowheads a P&ID does not.
    "03_distillation_train": "a bordered PFD sized to its own drawing",
    # A model rather than a sheet: no page, no furniture, so the drawing keeps
    # its own coordinates. This is what an unpaged export looks like.
    "04_control_loop": "the unpaged model, at the drawing's own coordinates",
    # Blocks and nothing else, which is the one diagram whose every symbol is
    # draw.io's default vertex.
    "12_block_flow_diagram": "a block flow diagram, drawn from plain rectangles",
}

OUT = ROOT / "drawio-samples"


def _gallery():
    """`scripts/gallery.py`, imported as a module.

    By path rather than by name: `scripts/` is not a package and is not on
    `sys.path` for anyone who has not put it there, and `tests/test_drawio.py`
    loads it exactly this way for exactly that reason.
    """
    spec = importlib.util.spec_from_file_location("_pandid_gallery", HERE / "gallery.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


#: What ``to_drawio`` takes. The example's own options are handed to it and the
#: rest are dropped **loudly** rather than quietly: `to_drawio` refuses an
#: option it cannot honour, so passing them straight through would simply raise,
#: and passing them through a silent filter would write a sample that is not the
#: sheet without saying so. `03`, `08`, `09`, `10` and `13` all ask for a stream
#: table, which the exporter now docks and rules like the sheet does.
#: `connections` was missing from this list while the exporter honoured it, so
#: the committed sample of the one flanged sheet in the corpus was the only
#: picture of it a reader could open and its joints were not in it. What is left
#: to drop is `02`'s debug overlay, which is scaffolding rather than drawing.
#: See `DrawioRenderer.render`, and `_DRAWIO_KWARGS` in `tests/test_drawio.py`,
#: which is the same list and has to stay the same list.
_EXPORTED = ("diagram", "page_size", "border", "show_stream_table", "connections")


def sample(stem: str) -> "tuple[str, list[str]]":
    """The ``.drawio`` document *stem*'s example exports, and what was dropped.

    The options are the example's own, which is what makes the committed file
    the one the library actually produces rather than one produced by a
    different set of arguments.
    """
    gallery = _gallery()
    fs, kwargs = gallery.flowsheet(stem)
    dropped = sorted(k for k in kwargs if k not in _EXPORTED)
    return (fs.to_drawio(**{k: v for k, v in kwargs.items() if k in _EXPORTED}),
            dropped)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("stems", nargs="*", metavar="STEM",
                        help=f"which samples to write, from {', '.join(sorted(SAMPLES))} "
                             f"(default: all of them)")
    args = parser.parse_args()

    unknown = [stem for stem in args.stems if stem not in SAMPLES]
    if unknown:
        raise SystemExit(f"not a sample: {', '.join(unknown)}\n"
                         f"the samples are {', '.join(sorted(SAMPLES))}")
    OUT.mkdir(exist_ok=True)
    for stem in args.stems or sorted(SAMPLES):
        path = OUT / f"{stem}.drawio"
        document, dropped = sample(stem)
        path.write_text(document, encoding="utf-8")
        note = f"  (without {', '.join(dropped)})" if dropped else ""
        print(f"wrote {path.relative_to(ROOT)}  -- {SAMPLES[stem]}{note}")


if __name__ == "__main__":
    main()
