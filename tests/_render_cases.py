"""Example flowsheets and render options for the regression corpus."""

import copy
import importlib.util
from functools import partial
from pathlib import Path
from typing import Any

from pandid import Flowsheet


def _generator():
    """Load the gallery generator module.

    Returns
    -------
    module
        Imported ``scripts/gallery.py`` module.
    """
    path = Path(__file__).resolve().parent.parent / "scripts" / "gallery.py"
    spec = importlib.util.spec_from_file_location("_pandid_script_gallery", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gallery = _generator()


def _build(stem: str) -> Flowsheet:
    """Build one example without writing its output files.

    Parameters
    ----------
    stem : str
        Example filename stem.

    Returns
    -------
    Flowsheet
        Fresh flowsheet captured from the example.
    """
    return gallery.flowsheet(stem)[0]


# Capture options once; builders return a new mutable model on every call.
SCENARIOS = {stem: (partial(_build, stem), gallery.flowsheet(stem)[1]) for stem in gallery.sheets()}


def copy_settled_case(
    cases: dict[str, tuple[Flowsheet, dict[str, Any]]], stem: str
) -> tuple[Flowsheet, dict[str, Any]]:
    """Copy one cached gallery case for a test that may mutate it.

    Parameters
    ----------
    cases : dict[str, tuple[Flowsheet, dict[str, Any]]]
        Settled gallery flowsheets and their render options.
    stem : str
        Gallery example name.

    Returns
    -------
    tuple[Flowsheet, dict[str, Any]]
        Independent flowsheet and render options.
    """
    fs, kwargs = cases[stem]
    return copy.deepcopy(fs), kwargs.copy()
