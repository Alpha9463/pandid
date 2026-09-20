"""Example flowsheets and render options for the regression corpus."""

import importlib.util
from functools import partial
from pathlib import Path

from pandid import Flowsheet


def _generator():
    """Load the gallery script used to capture example render calls."""
    path = Path(__file__).resolve().parent.parent / "scripts" / "gallery.py"
    spec = importlib.util.spec_from_file_location("_pandid_script_gallery", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gallery = _generator()


def _build(stem: str) -> Flowsheet:
    """Capture a fresh flowsheet without writing the example's output files."""
    return gallery.flowsheet(stem)[0]


# Capture options once; builders return a new mutable model on every call.
SCENARIOS = {stem: (partial(_build, stem), gallery.flowsheet(stem)[1]) for stem in gallery.sheets()}
