"""pfd — a Python engine for chemical-engineering Process Flow Diagrams.

Public API (topology layer)::

    from pfd import Flowsheet, Component, units
"""

# The one place the version is written: hatchling reads this literal at build
# time (`[tool.hatch.version]`), so the distribution metadata cannot disagree
# with what `import pfd` reports, and a source checkout reports the same string
# without the package having to be installed.
__version__ = "0.0.1"

from pfd.components import Component
from pfd.flowsheet import Flowsheet
from pfd import units
from pfd.spec import SpecError

__all__ = ["Flowsheet", "Component", "units", "SpecError", "__version__"]
