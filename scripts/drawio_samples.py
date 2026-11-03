#!/usr/bin/env python3
"""Generate representative Draw.io samples from gallery examples.

Run ``python scripts/drawio_samples.py`` after an example or exporter change
and review the generated files. A version-only package update needs no redraw.
"""

import argparse
import importlib.util
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

#: Representative examples that cover document, P&ID, PFD, and BFD exports.
SAMPLES = {
    "11_ethanol_pid": "a full P&ID on A3 paper, with every piece of furniture",
    "03_distillation_train": "a bordered PFD sized to its own drawing",
    "04_control_loop": "the unpaged model, at the drawing's own coordinates",
    "12_block_flow_diagram": "a block flow diagram, drawn from plain rectangles",
}

OUT = ROOT / "drawio-samples"


def _gallery():
    """Load the gallery generator module.

    Returns
    -------
    module
        Imported ``scripts/gallery.py`` module.
    """
    spec = importlib.util.spec_from_file_location("_pandid_gallery", HERE / "gallery.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


#: Example render options accepted by :meth:`pandid.Flowsheet.to_drawio`.
_EXPORTED = ("diagram", "page_size", "border", "show_stream_table", "connections")


def sample(stem: str) -> "tuple[str, list[str]]":
    """Export one example as a Draw.io document.

    Parameters
    ----------
    stem : str
        Example filename stem named in :data:`SAMPLES`.

    Returns
    -------
    tuple[str, list[str]]
        Draw.io document and sorted render-option names not supported by the
        exporter.
    """
    gallery = _gallery()
    fs, kwargs = gallery.flowsheet(stem)
    dropped = sorted(k for k in kwargs if k not in _EXPORTED)
    return (fs.to_drawio(**{k: v for k, v in kwargs.items() if k in _EXPORTED}), dropped)


def main() -> None:
    """Write requested Draw.io samples.

    Returns
    -------
    None
        Requested documents are written beneath :data:`OUT`.
    """
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "stems",
        nargs="*",
        metavar="STEM",
        help=f"which samples to write, from {', '.join(sorted(SAMPLES))} (default: all of them)",
    )
    args = parser.parse_args()

    unknown = [stem for stem in args.stems if stem not in SAMPLES]
    if unknown:
        raise SystemExit(
            f"not a sample: {', '.join(unknown)}\nthe samples are {', '.join(sorted(SAMPLES))}"
        )
    OUT.mkdir(exist_ok=True)
    for stem in args.stems or sorted(SAMPLES):
        path = OUT / f"{stem}.drawio"
        document, dropped = sample(stem)
        path.write_text(document, encoding="utf-8")
        note = f"  (without {', '.join(dropped)})" if dropped else ""
        print(f"wrote {path.relative_to(ROOT)}  -- {SAMPLES[stem]}{note}")


if __name__ == "__main__":
    main()
