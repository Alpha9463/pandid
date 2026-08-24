"""pandid: a Python engine for chemical-engineering Process Flow Diagrams.

Public API (topology layer)::

    from pandid import Flowsheet, Component, Separator, Cyclone

:mod:`pandid.units` is the ``kind`` + ``variant`` model a sheet is drawn from;
:mod:`pandid.devices` is one class per device the registry draws. They are one
hierarchy and not two -- a :class:`~pandid.devices.Cyclone` *is* a
:class:`~pandid.units.Separator` -- so every public name in both is re-exported
here and a sheet needs one spelling for the pair: ``pandid.Separator`` and
``pandid.units.Separator`` are the same class, as are ``pandid.Cyclone`` and
``pandid.devices.Cyclone``.

Both namespaces stay importable (``from pandid import units, devices``) for
anyone who would rather qualify, and for the ``units.Kind(variant=...)`` escape
hatch that reaches the drawings no class of their own is named for.

The handles the topology hands back -- a :class:`~pandid.streams.Stream` from
``connect()``, a :class:`~pandid.loops.Loop` from ``add_loop()`` -- are here for
the same reason the classes are: ``docs/api.md`` names them, and a name the
reference puts in a return position is a name the reader annotates with. The
rule the reference and this list are held to, by
``tests/test_documented_types.py``, is that a type the documentation names
*bare* is importable from ``pandid``, and a type that is not is named with the
module it lives in -- ``pandid.state.State``,
``pandid.document.StreamTableOptions``, ``pandid.render.symbols.Symbol``.
"""

# The one place the version is written: hatchling reads this literal at build
# time (`[tool.hatch.version]`), so the distribution metadata cannot disagree
# with what `import pandid` reports, and a source checkout reports the same string
# without the package having to be installed.
__version__ = "0.1.3"

from pandid.components import Component
from pandid.flowsheet import Flowsheet
from pandid import units
from pandid import devices
# The unit and device classes are names a user types, so they are on the package
# the way Flowsheet is. Both stars, because one hierarchy is spelled one way:
# ``units.Separator`` beside a bare ``Cyclone`` was two spellings for a base
# class and its own subclass, a distinction the import line made and the type
# system does not.
#
# The star is what keeps that free of a list this file maintains, and neither
# ``__all__`` it takes is one kept by hand alone: ``devices.__all__`` is written
# by scripts/gen_devices.py, and ``units.__all__`` is written beside the classes
# and held to *every* public Unit subclass in that module by
# tests/test_units_api.py. So a class added to either lands here with no second
# list to keep in step, which a literal of thirty unit names and forty-two
# device names would not be.
#
# Nothing collides. ``units.__all__`` and ``devices.__all__`` are disjoint -- a
# device class is named for the equipment and its base for the kind -- and
# neither holds ``Flowsheet``, ``Component``, ``SpecError``, ``units`` or
# ``devices``. Both facts are asserted rather than assumed, since a star import
# that shadowed one of these would do it silently.
from pandid.units import *  # noqa: F403
from pandid.devices import *  # noqa: F403
from pandid.spec import SpecError

# The objects the topology hands back, and the two furniture pairs a sheet is
# titled and annotated with. Every one of them is named in docs/api.md as the
# type of something the reader is holding -- ``connect() -> Stream``,
# ``validate() -> list[Issue]``, ``fs.loops: list[Loop]``, ``stream.route:
# Route | None`` -- and until #441 none of them could be spelled without
# reaching into a submodule the reference never mentioned. A reader who
# followed the documentation exactly got an ImportError, which for a package
# that ships ``py.typed`` and asks to be annotated against is the documentation
# describing an API that is not there.
#
# A list and not a star, because these modules are not the units/devices pair:
# each holds internals beside the one or two classes the reference names, and a
# star would export the module's whole namespace on every future addition.
# tests/test_documented_types.py is what keeps the list in step -- it re-derives
# the documented types from docs/api.md and fails on a name this list has not
# caught up with.
from pandid.ports import Port
from pandid.streams import Stream
from pandid.geometry import Pin, Frame, Route
from pandid.loops import Loop, ControlLoop
from pandid.stations import ValveStation
from pandid.validate import Issue
from pandid.document import TitleBlock, Revision, Annotation, TableBox

# ``Unit`` comes with them, deliberately. It is the base a custom unit
# subclasses -- docs/api.md, "Custom equipment" -- so it is a name a user types
# even though it is not one they instantiate, which is the footing ``SpecError``
# has been on here since 0.1.0. Holding it back would also cost the rule this
# file follows its statement: "every public name in units and devices" is a rule
# a reader can check against the modules, while "every public name except the
# one you subclass" is a list wearing a rule's clothes.
__all__ = ["Flowsheet", "Component", "units", "devices", "SpecError", "__version__",
           # The documented handles, in the order a sheet meets them.
           "Port", "Stream", "Pin", "Frame", "Route",
           "Loop", "ControlLoop", "ValveStation", "Issue",
           "TitleBlock", "Revision", "Annotation", "TableBox",
           *units.__all__, *devices.__all__]
