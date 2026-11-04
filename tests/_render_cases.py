"""Example flowsheets and render options for the regression corpus."""

import copy
import importlib.util
from functools import cache
from pathlib import Path
from typing import Any

from pandid import Flowsheet


@cache
def _script(name: str) -> Any:
    """Import a script from ``scripts/`` by name, once."""
    path = Path(__file__).resolve().parent.parent / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_pandid_script_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gallery = _script("gallery")

# Capture options once; builders return a new mutable model on every call.
SCENARIOS = {
    stem: (lambda stem=stem: gallery.flowsheet(stem)[0], kwargs)
    for stem, (_fs, kwargs) in gallery.captures().items()
}


def copy_settled_case(
    cases: dict[str, tuple[Flowsheet, dict[str, Any]]], stem: str
) -> tuple[Flowsheet, dict[str, Any]]:
    """Copy one cached gallery case for a test that may mutate it."""
    fs, kwargs = cases[stem]
    return copy.deepcopy(fs), kwargs.copy()
