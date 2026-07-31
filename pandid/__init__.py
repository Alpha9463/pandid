"""pandid: a Python engine for chemical-engineering Process Flow Diagrams.

Public API (topology layer)::

    from pandid import Flowsheet, Component, units, devices

:mod:`pandid.units` is the ``kind`` + ``variant`` model a sheet is drawn from;
:mod:`pandid.devices` is one class per device the registry draws, and every one
of its names is re-exported here, so ``pandid.Cyclone`` and
``pandid.devices.Cyclone`` are the same class.
"""

# The one place the version is written: hatchling reads this literal at build
# time (`[tool.hatch.version]`), so the distribution metadata cannot disagree
# with what `import pandid` reports, and a source checkout reports the same string
# without the package having to be installed.
__version__ = "0.1.1"

from pandid.components import Component
from pandid.flowsheet import Flowsheet
from pandid import units
from pandid import devices
# The device classes are names a user types, so they are on the package the way
# Flowsheet is. The star is deliberate and the list it takes is generated:
# ``devices.__all__`` is written by scripts/gen_devices.py, so a class added
# there is exported here without a second list to keep in step.
from pandid.devices import *  # noqa: F403
from pandid.spec import SpecError

__all__ = ["Flowsheet", "Component", "units", "devices", "SpecError", "__version__",
           *devices.__all__]
