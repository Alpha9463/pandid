"""``VARIANTS``: a class refuses a drawing it does not own, at construction.

A variant is a visual style within a functional type, and a base class owns
every one of its kind's: ``Separator`` draws the flash drum, the cyclone and the
sifter alike, so nothing it is handed can be wrong until the registry is asked
for the artwork, which is where it has always been checked. A class that names
its :attr:`~pandid.units.Unit.VARIANTS` is saying the opposite -- that the rest
belong to some other device -- and this suite is the contract that mechanism
owes its two audiences.

The first is **every sheet already drawn**. The shipped classes name no variants,
so the check is inert for them, and the sweep at the top of this module holds
every class against every variant the registry has for its kind to say so.

The second is the **generated per-variant classes** that come next: a class body
with a ``PORTS`` list and nothing else, inheriting its base's ``__init__``. That
is what ``_variant_ports`` exists for, and the throwaway subclasses below are
that shape written by hand, so the base is proved to support them before a
generator emits one.
"""

import pytest

from pandid import Flowsheet, units
from pandid.render.symbols import default_registry


def _unit_classes():
    """Every ``Unit`` subclass the package defines, transitively.

    Filtered to ``pandid``'s own modules, so the fixtures further down this file
    -- and any other test module that subclasses ``Unit`` -- are not swept up as
    if they were shipped API. Copied from ``tests/test_port_annotations.py``
    rather than shared, because the two suites ask different questions of the
    same list and neither should be able to narrow the other's.
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


def _shipped_cases():
    """Every ``(class, variant)`` a user can ask the library for today.

    A kind with no artwork registered (``Unit`` itself, and the two abstract
    bases) still has ``"default"``, which is what its constructor defaults to.
    """
    return [
        (cls, variant)
        for cls in _unit_classes()
        for variant in (default_registry.variants(cls.kind) or ["default"])
    ]


_CASE_IDS = [f"{cls.__name__}-{variant}" for cls, variant in _shipped_cases()]


# ---------------------------------------------------------------------------
# Compatibility: nothing the library ships may move
# ---------------------------------------------------------------------------


def test_no_shipped_class_names_its_variants():
    """The check is inert for everything in the port table, and this is why.

    Stated once, directly, because every other compatibility claim in this file
    follows from it: a class with an empty ``VARIANTS`` never reaches the raise,
    so ``Separator(variant="cyclone")`` runs the code it always ran. When the
    generated classes land, this test is the one that has to be rewritten
    deliberately rather than the sweep quietly changing meaning.
    """
    named = {cls.__name__: cls.VARIANTS for cls in _unit_classes() if cls.VARIANTS}
    assert named == {}


@pytest.mark.parametrize(("cls", "variant"), _shipped_cases(), ids=_CASE_IDS)
def test_every_shipped_variant_still_constructs(cls, variant):
    """Construction is not where a shipped ``Kind(variant=...)`` can fail.

    Every unit takes its name as the first positional argument, so one call
    builds any of them; the variant is the only thing varying here.
    """
    assert cls("X-1", variant=variant).variant == variant


@pytest.mark.parametrize(("cls", "variant"), _shipped_cases(), ids=_CASE_IDS)
def test_a_shipped_variant_resolves_the_nozzles_it_always_did(cls, variant):
    """The ports, against the expression that built them before this change.

    Two rules covered the whole library and still do. The two variant-port
    classes appended ``_VARIANT_PORTS.get(variant, <their default>)`` after
    ``super().__init__()``, which is spelled out here from their own tables
    rather than taken from the new ``_variant_ports``, so the assertion is
    independent of the thing it is checking. Every other class builds the same
    nozzles whatever the variant, since a variant is a second drawing of one
    functional type, so its answer is the class's own default-variant instance.
    """
    built = set(cls("X-1", variant=variant).ports)
    if cls is units.HeatExchanger:
        table = cls._VARIANT_PORTS.get(variant, cls._SHELL_AND_TUBE)
        assert built == {spec[0] for spec in table}
    elif cls is units.Separator:
        table = cls._VARIANT_PORTS.get(variant, cls._PHASES)
        assert built == {spec[0] for spec in table}
    else:
        assert built == set(cls("X-1").ports)


def test_a_base_class_still_refuses_an_unknown_variant_at_render():
    """The old error, in the old place, for the classes that set no ``VARIANTS``.

    Moving the complaint forward to construction is the point of ``VARIANTS``,
    and a class that owns its whole kind has no list to move it forward *from*:
    only the registry knows what artwork exists. So this path is not replaced,
    it is the one everything shipped today still takes.
    """
    fs = Flowsheet("F")
    fs.add(units.Separator("S-1", variant="draft_tube"))
    with pytest.raises(ValueError, match="separator has no variant 'draft_tube'"):
        fs.to_svg()


# ---------------------------------------------------------------------------
# The per-variant subclass: what the generated classes will be
# ---------------------------------------------------------------------------


class _Kettle(units.HeatExchanger):
    """A generated exchanger class, written by hand: a class body and no more.

    It declares its whole nozzle list, the variant's own ``bottoms`` included,
    and inherits ``HeatExchanger.__init__``. That constructor adds the variant's
    nozzles after ``super().__init__()`` has added ``PORTS``, so before
    ``_variant_ports`` asked whether the class had declared any, this class
    raised ``"already has a port named 'shell_in'"`` on construction.
    """

    VARIANTS = ("kettle",)
    PORTS = [
        ("shell_in", "inlet", "process"),
        ("shell_out", "outlet", "process"),
        ("tube_in", "inlet", "process"),
        ("tube_out", "outlet", "process"),
        ("bottoms", "outlet", "liquid"),
    ]


class _Sifter(units.Separator):
    """The same shape against ``Separator``, whose variant nozzles differ in name.

    A mechanical separator draws off ``overflow`` and ``underflow`` instead of
    ``vapor`` and ``liquid``, which is the case a declared ``PORTS`` list has to
    be able to state without the base's default pair arriving as well.
    """

    VARIANTS = ("sifter",)
    PORTS = [
        ("feed", "inlet", "feed"),
        ("overflow", "outlet", "process"),
        ("underflow", "outlet", "process"),
    ]


class _Cyclone(units.Separator):
    """A per-variant class that declares no ports, so it inherits the variant's.

    The guard is keyed on the declaration and not on being a subclass, which is
    what lets a generated class say nothing about nozzles where the base's
    variant table already says the right thing.
    """

    VARIANTS = ("cyclone",)


class _Screen(units.Separator):
    """A class that renames a variant, and lists both spellings.

    ``VARIANT_ALIASES`` is what makes ``screen`` reach the ``sifter`` artwork.
    The registry's spelling is in ``VARIANTS`` as well, deliberately: what is
    stored is the registry name, so that is what a written-out spec carries and
    what the class has to accept when the spec is read back.
    """

    VARIANTS = ("screen", "sifter")
    VARIANT_ALIASES = {"screen": "sifter"}


class _Knockout(units.Separator):
    """A per-variant class that is built by naming it and nothing else.

    ``variant`` defaults to ``"default"``, so a class naming its variants has to
    say what that means for it. Listing ``"default"`` and aliasing it is the
    whole answer: no second class attribute, and no ``__init__`` of its own,
    which is the property a generated class is worth having.
    """

    VARIANTS = ("default", "knockout")
    VARIANT_ALIASES = {"default": "knockout"}


@pytest.mark.parametrize("cls", [_Kettle, _Sifter], ids=lambda c: c.__name__)
def test_a_subclass_declaring_its_own_ports_builds_exactly_those(cls):
    """The contract the generated classes rely on, against both variant bases.

    Exactly the declared nozzles, in declaration order, and no duplicate-port
    ``ValueError`` from the base's ``__init__`` running its variant loop on top
    of them.
    """
    unit = cls("X-1", variant=cls.VARIANTS[0])
    assert list(unit.ports) == [spec[0] for spec in cls.PORTS]


def test_a_subclass_declaring_no_ports_still_gets_the_variants():
    """...and the inherited path is untouched for one that declares none."""
    assert set(_Cyclone("S-1", variant="cyclone").ports) == {"feed", "vapor", "liquid"}


def test_an_alias_stores_the_registry_spelling():
    """What ``self.variant`` holds, and what reads it.

    ``SymbolRegistry.for_unit`` and ``pandid.portgeom`` find the artwork through
    this attribute, so a name only one class knows would find none.
    """
    assert _Screen("S-1", variant="screen").variant == "sifter"
    assert _Screen("S-2", variant="sifter").variant == "sifter"


def test_an_alias_resolves_the_ports_of_the_variant_it_names():
    """The nozzles follow the registry spelling, not the class-local one.

    ``_VARIANT_PORTS`` is keyed the way the registry spells a variant, so the
    lookup has to happen after the alias has been applied: a ``Screen`` gets the
    sifter's ``overflow``/``underflow``, not the flash drum's phases.
    """
    assert set(_Screen("S-1", variant="screen").ports) == {"feed", "overflow", "underflow"}


def test_a_class_can_alias_default_onto_its_own_drawing():
    """Naming the class alone asks for the class's drawing, not the kind's.

    Without this the constructor's ``variant="default"`` would be the one name a
    per-variant class refuses, and every one of them would need an ``__init__``
    to change the default -- which is the per-class code ``_variant_ports``
    exists to avoid emitting.
    """
    assert _Knockout("S-1").variant == "knockout"
    assert _Knockout("S-2", variant="knockout").variant == "knockout"


def test_a_renamed_variant_reads_back_the_spelling_it_writes():
    """The round trip a spec makes, without needing a spec to make it.

    ``to_dict()`` writes ``self.variant``, which is the registry's spelling, so
    the class-local rename is not in the file. Listing both names is what keeps
    the file readable back by the class that wrote it, and this is that trip:
    construct by the local name, read what was stored, construct again from it.
    """
    stored = _Screen("S-1", variant="screen").variant
    assert _Screen("S-2", variant=stored).variant == stored


# ---------------------------------------------------------------------------
# The refusal itself
# ---------------------------------------------------------------------------


def test_a_variant_belonging_to_another_device_is_refused_at_construction():
    """The whole point: the line that asks for it is the line that fails."""
    with pytest.raises(ValueError) as excinfo:
        _Cyclone("S-1", variant="sifter")
    message = str(excinfo.value)
    assert message.startswith("S-1: _Cyclone draws 'cyclone', not 'sifter'.")


def test_the_refusal_teaches_the_low_level_form():
    """A refused variant is not a dead end, and the message says so.

    The drawing exists and is in the catalogue; the base class that owns the
    whole kind draws every one of them, so naming it is the difference between
    "you cannot have this" and "ask for it this way".
    """
    with pytest.raises(ValueError, match=r"Separator\(variant='sifter'\)") as excinfo:
        _Cyclone("S-1", variant="sifter")
    assert "any variant registered for a separator" in str(excinfo.value)


def test_a_near_miss_is_suggested():
    with pytest.raises(ValueError, match=r"did you mean 'cyclone'\?"):
        _Cyclone("S-1", variant="cylone")


def test_a_class_with_no_generic_ancestor_offers_no_low_level_form():
    """A custom class straight off ``Unit`` has nowhere to send an author.

    ``Unit`` draws a generic box under ``kind = "unit"``, so offering it as the
    low-level form would point at artwork that is not this class's. The rest of
    the message stands; only the escape hatch is dropped.
    """

    class _Crystalliser(units.Unit):
        kind = "crystalliser_variant_test"
        VARIANTS = ("default", "forced_circulation")

    with pytest.raises(ValueError) as excinfo:
        _Crystalliser("CR-1", variant="draft_tube")
    message = str(excinfo.value)
    assert "belongs to whichever class draws it." in message
    assert "generic form" not in message
