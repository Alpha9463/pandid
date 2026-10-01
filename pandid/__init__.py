"""pandid: draw process flow diagrams and P&IDs from a Python flowsheet.

Public API::

    from pandid import Flowsheet, Component, Separator, Cyclone

:mod:`pandid.units` holds the base unit classes, drawn by ``kind`` and
``variant``; :mod:`pandid.devices` holds one class per registered drawing.
They form one hierarchy (a :class:`~pandid.devices.Cyclone` is a
:class:`~pandid.units.Separator`), and every public name in both is
re-exported here, so ``pandid.Separator`` is ``pandid.units.Separator``.
Both modules also stay importable for qualified use and for
``units.Kind(variant=...)``.

The handles the API returns, such as :class:`~pandid.streams.Stream` from
``connect()`` and :class:`~pandid.loops.Loop` from ``add_loop()``, are also
exported for imports and type annotations.
"""

# The only place the version is written; hatchling reads it at build time.
__version__ = "0.1.5"

from pandid.components import Component
from pandid.flowsheet import Flowsheet
from pandid import units
from pandid import devices
# Re-export both class modules. Their ``__all__`` lists are generated or tested
# (scripts/gen_devices.py, tests/test_units_api.py), disjoint from each other,
# and free of the names imported here, so no list is kept in this file.
from pandid.units import *  # noqa: F403
from pandid.devices import *  # noqa: F403
from pandid.spec import SpecError

# Handles the API returns and the title-block and annotation classes, all named
# in docs/api.md. Listed explicitly so these modules' internals stay private;
# tests/test_units_api.py checks the bindings.
from pandid.ports import Port
from pandid.streams import Stream
from pandid.geometry import Pin, Frame, Route
from pandid.loops import Loop, ControlLoop
from pandid.stations import ValveStation
from pandid.validate import Issue
from pandid.document import TitleBlock, Revision, Annotation, TableBox

# ``Unit`` is exported through units.__all__ because custom units subclass it.
__all__ = ["Flowsheet", "Component", "units", "devices", "SpecError", "__version__",
           "Port", "Stream", "Pin", "Frame", "Route",
           "Loop", "ControlLoop", "ValveStation", "Issue",
           "TitleBlock", "Revision", "Annotation", "TableBox",
           *units.__all__, *devices.__all__]
