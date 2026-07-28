"""pandid: a Python engine for chemical-engineering Process Flow Diagrams.

Public API (topology layer)::

    from pandid import Flowsheet, Component, units
"""

# The one place the version is written: hatchling reads this literal at build
# time (`[tool.hatch.version]`), so the distribution metadata cannot disagree
# with what `import pandid` reports, and a source checkout reports the same string
# without the package having to be installed.
__version__ = "0.1.0rc1"

from pandid.components import Component
from pandid.flowsheet import Flowsheet
from pandid import units
from pandid.spec import SpecError

__all__ = ["Flowsheet", "Component", "units", "SpecError", "__version__"]
