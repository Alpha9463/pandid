"""The port annotations and the ports themselves must say the same thing.

Every unit class writes its nozzles down twice: once as the ``PORTS`` tuples (or
the ``__init__`` calls) that build them, and once as bare ``suction: Port``
annotations that let mypy and an editor see them. Two spellings of one fact
drift, and this suite is what stops them: it walks every ``Unit`` subclass the
package defines, builds one, and checks the two halves against each other in
both directions.

Found rather than listed, so a class added tomorrow is covered without anyone
remembering to come here. The exemptions are named, and there are only three
kinds, each argued at the class or the module it applies to:

- the **numbered families** (``Mixer``'s ``in_1`` ... ``in_n``, ``Splitter``'s
  ``out_1`` ... ``out_n``, and both of ``Block``'s), whose size is the caller's,
  so there is no finite set of names a class annotation could stand for.
  ``Block`` is the one class with *nothing* left over to declare, since every
  connection it has is one of the two families;
- the **variant nozzles** (``HeatExchanger``'s ``bottoms``, ``Separator``'s
  ``overflow``), which belong to some variants and not others, so declaring them
  on the base class would tell a checker something false about every other one;
- the **superseded nozzles** of :mod:`pandid.devices`, where a generated class
  replaces its base's whole nozzle list. ``PlateExchanger`` has lettered sides
  and no shell, and ``CheckValve`` has no actuator, but both inherit the
  annotation their base wrote. Python has no way to un-declare one:
  ``__annotations__`` is merged down the MRO and there is no "delete", and
  re-annotating the name with something narrower is an incompatible override.
  So the phantom check answers for the annotations a class *writes*, and
  :func:`test_only_these_classes_supersede_a_declaration` is what keeps that
  from spreading past the twelve classes it is true of.
"""

import inspect
import re

import pytest

from pandid import devices, units
from pandid.ports import Port

# A nozzle whose name ends in an underscore and a number is one of a family
# sized at construction (Mixer(n_inlets=...), Splitter(n_outlets=...),
# Column/Reactor(n_feeds=...)). A class annotation is a statement about every
# instance of the class and the count is not in the type, so no annotation can
# cover them. They are exempt from the first half of the invariant and only
# from that half; test_only_the_named_families_are_exempt pins who may use it.
_NUMBERED = re.compile(r"_\d+$")

# The classes whose default construction produces a numbered family. Column and
# Reactor are absent on purpose: they default to one feed, which is spelled
# ``feed`` and is therefore declared like any other fixed nozzle.
#
# ``Block`` joins the list deliberately rather than by slipping past the
# name-shaped exemption: a block flow diagram's box has no nozzle every block
# has, so *all* of its connections are numbered and it declares no annotations
# at all. Its own class comment argues that; this is the second half of the
# decision, and the reason a fourth entry has to be added by hand.
_VARIABLE_PORT_CLASSES = {units.Mixer, units.Splitter, units.Block}


def _unit_classes():
    """Every ``Unit`` subclass the package defines, transitively.

    Filtered to ``pandid``'s own modules, because a test module that subclasses
    ``Unit`` to exercise the custom-unit workflow (``tests/test_custom_units.py``
    does, and the docs tell users to) is a fixture, not part of the shipped API,
    and pytest has already imported it by the time this runs.
    """
    found: dict[type, None] = {}
    pending = [units.Unit]
    while pending:
        cls = pending.pop()
        if cls in found or not cls.__module__.startswith("pandid."):
            continue
        found[cls] = None
        pending.extend(cls.__subclasses__())
    return list(found)


def _annotated(cls):
    """The nozzle names ``cls`` declares, its own and its bases'."""
    # get_type_hints, not __annotations__: units.py has `from __future__ import
    # annotations`, so every annotation is a string until something evaluates
    # it, and only get_type_hints walks the MRO and resolves each base's
    # strings against the module that wrote them. Comparing `is Port` rather
    # than by name is what keeps `kind: str`, `PORTS: list[...]` and the layout
    # engine's `_slot` out of the answer.
    import typing

    return {name for name, hint in typing.get_type_hints(cls).items() if hint is Port}


def _superseded(cls):
    """Annotations ``cls`` inherits for nozzles its own ``PORTS`` replaced.

    A class that declares ``PORTS`` replaces its base's list outright, which is
    what :meth:`~pandid.units.Unit._declared_ports` means by "the nearest
    declaration is the whole list". The base's *annotations* do not go with it,
    because nothing in Python removes an inherited one -- so these are the names
    a checker still resolves and a runtime lookup no longer finds.

    Read off the class's *own* annotations rather than ``get_type_hints``, which
    merges the MRO; that is what tells "written here" from "inherited", and it
    is why the exemption cannot leak to a class that simply forgot to declare a
    nozzle it builds.
    """
    if "PORTS" not in vars(cls):
        return set()
    return _annotated(cls) - _own_annotated(cls) - _built(cls)


def _own_annotations(cls):
    """The annotations written in ``cls``'s own body, resolved.

    ``inspect.get_annotations`` and not ``cls.__dict__["__annotations__"]``,
    because where a class keeps them is a 3.10-through-3.14 difference and this
    package supports all five: PEP 649 made them lazy in 3.14, so the dict holds
    an ``__annotate_func__`` until something asks. This asks. It is also the one
    reader that answers for a single class rather than for the whole MRO, which
    is the distinction the exemption above turns on.
    """
    return inspect.get_annotations(cls, eval_str=True)


def _own_annotated(cls):
    """The nozzle names ``cls`` declares in its own body."""
    return {name for name, hint in _own_annotations(cls).items() if hint is Port}


def _built(cls):
    """The nozzle names one default instance of ``cls`` actually has.

    Every unit takes its name as the first positional argument (an Instrument's
    is its tag, a Tee's is optional), so one call constructs any of them, and
    the default of every other argument is what "default construction" means
    here: the variant, and the feed/inlet/outlet count, that a user gets by
    naming the class and nothing else.
    """
    return set(cls("X-1").ports)


@pytest.mark.parametrize("cls", _unit_classes(), ids=lambda c: c.__name__)
def test_every_port_built_is_annotated(cls):
    """A nozzle the class creates is a nozzle a type checker can see.

    The direction that catches the omission: someone adds a nozzle to ``PORTS``
    and the attribute stays invisible to mypy, which is the state this whole
    layer exists to leave behind.
    """
    missing = {name for name in _built(cls) - _annotated(cls) if not _NUMBERED.search(name)}
    assert not missing, (
        f"{cls.__name__} builds {sorted(missing)} but does not declare "
        f"them; add `{sorted(missing)[0]}: Port` to the class body"
    )


@pytest.mark.parametrize("cls", _unit_classes(), ids=lambda c: c.__name__)
def test_every_annotation_is_a_port_that_is_built(cls):
    """A declared nozzle is one default construction really produces.

    The direction that catches the lie, and the reason ``Separator`` stops at
    ``feed``/``vapor``/``liquid`` and ``HeatExchanger`` at the shell and tube
    four: annotating a variant's nozzle here would promise it on every instance
    of the class, and mypy would then wave through a sheet that raises the
    moment it is drawn.
    """
    phantom = _annotated(cls) - _built(cls) - _superseded(cls)
    assert not phantom, (
        f"{cls.__name__} declares {sorted(phantom)}, which a default "
        f"{cls.__name__} does not have; a nozzle only some variants carry "
        f"belongs on a per-variant subclass, not here"
    )


def test_only_the_named_families_are_exempt():
    """Nobody else may quietly take the numbered-family exemption.

    The exemption above is keyed on the *shape* of a name, so a new class with
    numbered nozzles would slip through the first test without anyone deciding
    that it should. Naming the two classes that have them makes adding a third
    a deliberate act with this docstring to read first.
    """
    variable = {cls for cls in _unit_classes() if any(_NUMBERED.search(p) for p in _built(cls))}
    assert variable == _VARIABLE_PORT_CLASSES


def test_only_these_classes_supersede_a_declaration():
    """The generated classes whose base annotates a nozzle they do not build.

    Listed rather than counted, because each one is a checker resolving an
    attribute that raises at runtime, and that is the cost of the layer stated
    outright. Two shapes of it, and no others:

    - the six separators that draw off ``overflow``/``underflow`` where
      ``Separator`` annotates ``vapor``/``liquid``;
    - the four exchangers whose sides are not a shell and tubes, plus
      ``CheckValve``, which has no actuator to declare.

    A name appearing here that is not one of those is a nozzle somebody dropped,
    not a vocabulary somebody replaced.
    """
    superseded = {
        cls.__name__: sorted(_superseded(cls)) for cls in _unit_classes() if _superseded(cls)
    }
    assert superseded == {
        "Cyclone": ["liquid", "vapor"],
        "GravitySeparator": ["liquid", "vapor"],
        "ElectrostaticPrecipitator": ["liquid", "vapor"],
        "Screen": ["liquid", "vapor"],
        "ImpactSeparator": ["liquid", "vapor"],
        "MagneticSeparator": ["liquid", "vapor"],
        "AirCooledExchanger": ["shell_in", "shell_out"],
        "PlateExchanger": ["shell_in", "shell_out", "tube_in", "tube_out"],
        "SpiralExchanger": ["shell_in", "shell_out", "tube_in", "tube_out"],
        "ThinFilmEvaporator": ["shell_in", "shell_out", "tube_in", "tube_out"],
        "CheckValve": ["actuator"],
    }


def test_every_generated_class_writes_its_own_nozzle_declarations():
    """The direction the exemption above must not weaken.

    A generated class declares ``PORTS``, so the phantom check stops asking
    about what it inherited -- which would be a hole if it were also allowed to
    inherit the annotations for the nozzles it *does* build. It is not: every
    one of them is written in the class body, which is what makes the emitted
    file readable as the declaration it is.
    """
    for name in devices.__all__:
        cls = getattr(devices, name)
        assert {port for port, _, _ in cls.PORTS} <= _own_annotated(cls), (
            f"{name} builds nozzles it does not declare in its own body"
        )


@pytest.mark.parametrize(
    ("cls", "variant", "nozzle"),
    [
        (units.HeatExchanger, "kettle", "bottoms"),
        (units.Separator, "sifter", "overflow"),
        (units.Separator, "sifter", "underflow"),
        (units.HeatExchanger, "plate", "side_a_in"),
    ],
)
def test_variant_nozzles_exist_but_are_not_declared_on_the_base(cls, variant, nozzle):
    """The variant nozzles are real, and are still reached by name at runtime.

    Stated separately from the two invariants above because it is the *reason*
    for the second one, and because it is what the follow-up change (a generated
    subclass per variant) has to satisfy: these names move onto those classes,
    and this test is where it will show.
    """
    assert nozzle in cls("X-1", variant=variant).ports
    assert nozzle not in _annotated(cls)


@pytest.mark.parametrize("cls", _unit_classes(), ids=lambda c: c.__name__)
def test_annotations_bind_nothing(cls):
    """The declarations are annotations, never assignments.

    An annotation with a value would put a shared ``Port`` on the class, which
    every instance would then see until ``_add_port``'s ``setattr`` shadowed it,
    and a unit that failed to build one would silently answer with another
    unit's nozzle. Nothing about construction or the drawn sheet may change
    because of this layer, and this is the line that says so.
    """
    bound = {name for name in _annotated(cls) if name in vars(cls)}
    assert not bound, f"{cls.__name__} assigns {sorted(bound)} instead of only annotating"
