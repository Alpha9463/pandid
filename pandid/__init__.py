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
"""

# The one place the version is written: hatchling reads this literal at build
# time (`[tool.hatch.version]`), so the distribution metadata cannot disagree
# with what `import pandid` reports, and a source checkout reports the same string
# without the package having to be installed.
__version__ = "0.1.2"

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

# ``Unit`` comes with them, deliberately. It is the base a custom unit
# subclasses -- docs/api.md, "Custom equipment" -- so it is a name a user types
# even though it is not one they instantiate, which is the footing ``SpecError``
# has been on here since 0.1.0. Holding it back would also cost the rule this
# file follows its statement: "every public name in units and devices" is a rule
# a reader can check against the modules, while "every public name except the
# one you subclass" is a list wearing a rule's clothes.
__all__ = ["Flowsheet", "Component", "units", "devices", "SpecError", "__version__",
           *units.__all__, *devices.__all__]
