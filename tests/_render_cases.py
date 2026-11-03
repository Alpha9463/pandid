"""Example flowsheets and render options for the regression corpus."""

import copy
import importlib.util
from functools import cache, partial
from pathlib import Path
from typing import Any

from pandid import Flowsheet


@cache
def _script(name: str) -> Any:
    """Import a script from ``scripts/`` by name, once.

    Parameters
    ----------
    name : str
        Script stem.

    Returns
    -------
    module
        Imported script module.
    """
    path = Path(__file__).resolve().parent.parent / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_pandid_script_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gallery = _script("gallery")


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
