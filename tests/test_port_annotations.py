"""The port annotations and the ports themselves must say the same thing.

Every unit class writes its nozzles down twice: once as the ``PORTS`` tuples (or
the ``__init__`` calls) that build them, and once as bare ``suction: Port``
annotations that let mypy and an editor see them. Two spellings of one fact
drift, and this suite is what stops them: it walks every ``Unit`` subclass the
package defines, builds one, and checks the two halves against each other in
both directions.

Found rather than listed, so a class added tomorrow is covered without anyone
remembering to come here. The exemptions are named, and there are only two
kinds, both argued at the class they apply to:

- the **numbered families** (``Mixer``'s ``in_1`` ... ``in_n`` and ``Splitter``'s
  ``out_1`` ... ``out_n``), whose size is the caller's, so there is no finite
  set of names a class annotation could stand for;
- the **variant nozzles** (``HeatExchanger``'s ``bottoms``, ``Separator``'s
  ``overflow``), which belong to some variants and not others, so declaring them
  on the base class would tell a checker something false about every other one.
"""

import re

import pytest

from pandid import units
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
_VARIABLE_PORT_CLASSES = {units.Mixer, units.Splitter}


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
    phantom = _annotated(cls) - _built(cls)
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
