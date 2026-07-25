"""Let the examples run straight from a source checkout, from either directory.

``python examples/03_distillation_train.py`` and
``cd examples && python 03_distillation_train.py`` both work:

- Python puts the *script's* directory on ``sys.path``, not the repo root, so an
  un-installed checkout cannot ``import pfd``. This adds the repo root, but only
  when ``pfd`` is not already importable — an installed copy always wins.
- ``out()`` resolves an output filename next to the examples, so a rendered
  drawing lands in the same place no matter where you ran the script from.

Not needed once the package is installed (``pip install pfd`` or
``pip install -e .``); it just keeps the examples runnable without that step.
"""

import sys
from importlib.util import find_spec
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent

if find_spec("pfd") is None and str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def out(filename: str) -> str:
    """Absolute path to ``filename`` alongside the examples."""
    return str(_HERE / filename)
