"""Test ``VARIANTS``: a class accepts every variant of its kind and refuses the rest."""

import pytest

import pandid
from pandid import Flowsheet, devices, units
from pandid.render.symbols import default_registry
from test_placement import _shipped_unit_classes
from test_symbol_invariants import _drawing


def _unit_classes():
    """Return every ``Unit`` subclass :mod:`pandid.units` itself defines."""
    return [cls for cls in _shipped_unit_classes() if cls.__module__ == units.__name__]


def _shipped_cases():
    """Return every ``(class, variant)`` a user can ask the library for today."""
    return [
        (cls, variant)
        for cls in _unit_classes()
        for variant in (default_registry.variants(cls.kind) or ["default"])
    ]


_CASE_IDS = [f"{cls.__name__}-{variant}" for cls, variant in _shipped_cases()]


# --- Compatibility: nothing the library ships may move ---


def test_no_class_in_units_names_its_variants():
    """Check that no class in ``pandid.units`` names its ``VARIANTS``."""
    named = {cls.__name__: cls.VARIANTS for cls in _unit_classes() if cls.VARIANTS}
    assert named == {}


def test_every_generated_class_names_its_variants():
    """Check that every class in ``pandid.devices`` names its ``VARIANTS``."""
    silent = [name for name in devices.__all__ if not getattr(devices, name).VARIANTS]
    assert silent == []


@pytest.mark.parametrize(("cls", "variant"), _shipped_cases(), ids=_CASE_IDS)
def test_a_shipped_variant_resolves_the_nozzles_it_always_did(cls, variant):
    """Check that each shipped ``(class, variant)`` builds the nozzles its port tables give."""
    unit = cls("X-1", **_drawing(cls, variant))
    assert unit.variant == variant
    built = set(unit.ports)
    if cls is units.HeatExchanger:
        table = cls._VARIANT_PORTS.get(variant, cls._DEFAULT_PORTS)
        assert built == {spec[0] for spec in table}
    elif cls is units.Separator:
        # ``feed_1`` is the charge nozzle ``__init__`` adds.
        table = cls._VARIANT_PORTS.get(variant, cls._DEFAULT_PORTS)
        assert built == {spec[0] for spec in table} | {"feed_1"}
    elif cls in (units.Filter, units.Silo):
        table = cls._VARIANT_PORTS.get(variant, cls._DEFAULT_PORTS)
        assert built == {spec[0] for spec in table}
    elif cls is units.Tank:
        # ``in_1`` and ``out_1`` are the families ``__init__`` adds.
        table = cls._VARIANT_PORTS.get(variant, cls._DEFAULT_PORTS)
        assert built == {spec[0] for spec in table} | {"in_1", "out_1"}
    elif cls is units.Valve:
        table = cls._VARIANT_PORTS.get(variant, cls._DEFAULT_PORTS)
        assert built == {spec[0] for spec in table}
    elif cls is units.Reactor:
        table = cls._VARIANT_PORTS.get(variant, cls._DEFAULT_PORTS)
        want = {spec[0] for spec in table} | {"feed_1"}
        if variant in cls._STIRRED:
            want |= {"drive"}
        assert built == want
    else:
        assert built == set(cls("X-1").ports)


_EXPORTED_UNITS: list[type[units.Unit]] = [
    obj
    for obj in (getattr(pandid, name) for name in pandid.__all__)
    if isinstance(obj, type) and issubclass(obj, units.Unit)
]


@pytest.mark.parametrize("cls", _EXPORTED_UNITS, ids=[cls.__name__ for cls in _EXPORTED_UNITS])
def test_every_exported_unit_renders_without_a_variant(cls: type[units.Unit]) -> None:
    """Check that each exported unit class draws with its default variant."""
    fs = Flowsheet("F")
    fs.add(cls("X-1"))
    fs.to_svg()


def test_a_base_class_still_refuses_an_unknown_variant_at_render():
    """Check that a class with no ``VARIANTS`` refuses an unknown variant at render."""
    fs = Flowsheet("F")
    fs.add(units.Separator("S-1", variant="draft_tube"))
    with pytest.raises(ValueError, match="separator has no variant 'draft_tube'"):
        fs.to_svg()


# --- Hand-written per-variant subclasses ---


class _Kettle(units.HeatExchanger):
    """An exchanger subclass that declares the kettle variant's whole nozzle list."""

    VARIANTS = ("kettle",)
    PORTS = [
        ("shell_in", "inlet", "process"),
        ("shell_out", "outlet", "process"),
        ("tube_in", "inlet", "process"),
        ("tube_out", "outlet", "process"),
        ("bottoms", "outlet", "liquid"),
    ]


class _Sifter(units.Separator):
    """A separator subclass that declares the sifter variant's nozzle list."""

    VARIANTS = ("sifter",)
    PORTS = [
        ("feed", "inlet", "feed"),
        ("overflow", "outlet", "process"),
        ("underflow", "outlet", "process"),
    ]


class _Cyclone(units.Separator):
    """A per-variant class that declares no ports, so it inherits the variant's."""

    VARIANTS = ("cyclone",)


class _Screen(units.Separator):
    """A class that renames a variant, and lists both spellings."""

    VARIANTS = ("screen", "sifter")
    VARIANT_ALIASES = {"screen": "sifter"}


class _Knockout(units.Separator):
    """A per-variant class that aliases ``default`` onto its own drawing."""

    VARIANTS = ("default", "knockout")
    VARIANT_ALIASES = {"default": "knockout"}


@pytest.mark.parametrize("cls", [_Kettle, _Sifter], ids=lambda c: c.__name__)
def test_a_subclass_declaring_its_own_ports_builds_exactly_those(cls):
    """Check that a subclass declaring ``PORTS`` builds exactly those nozzles, in order."""
    unit = cls("X-1", variant=cls.VARIANTS[0])
    # Every separator's ``__init__`` also adds ``feed_1``.
    extra = ["feed_1"] if issubclass(cls, units.Separator) else []
    assert list(unit.ports) == [spec[0] for spec in cls.PORTS] + extra


def test_a_subclass_declaring_no_ports_still_gets_the_variants():
    """Check that a subclass declaring no ports gets the variant's nozzles."""
    assert set(_Cyclone("S-1", variant="cyclone").ports) == {"feed_1", "overflow", "underflow"}


def test_an_alias_stores_the_registry_spelling():
    """Check that an aliased variant stores the registry spelling in ``variant``."""
    assert _Screen("S-1", variant="screen").variant == "sifter"
    assert _Screen("S-2", variant="sifter").variant == "sifter"


def test_an_alias_resolves_the_ports_of_the_variant_it_names():
    """Check that an alias builds the nozzles of the registry variant it names."""
    assert set(_Screen("S-1", variant="screen").ports) == {"feed_1", "overflow", "underflow"}


def test_a_class_can_alias_default_onto_its_own_drawing():
    """Check that a class aliasing ``default`` builds its own drawing when named alone."""
    assert _Knockout("S-1").variant == "knockout"
    assert _Knockout("S-2", variant="knockout").variant == "knockout"


# --- The refusal itself ---


def test_a_variant_belonging_to_another_device_is_refused_at_construction():
    """Check that construction refuses a variant another device owns."""
    with pytest.raises(ValueError) as excinfo:
        _Cyclone("S-1", variant="sifter")
    message = str(excinfo.value)
    assert message.startswith("S-1: _Cyclone draws 'cyclone', not 'sifter'.")
    # The refusal names the base-class form that draws the variant.
    assert "Separator(variant='sifter')" in message
    assert "any variant registered for a separator" in message


def test_a_near_miss_is_suggested():
    with pytest.raises(ValueError, match=r"did you mean 'cyclone'\?"):
        _Cyclone("S-1", variant="cylone")


def test_a_class_with_no_generic_ancestor_offers_no_low_level_form():
    """Check that a class straight off ``Unit`` is refused without a low-level form."""

    class _Crystalliser(units.Unit):
        kind = "crystalliser_variant_test"
        VARIANTS = ("default", "forced_circulation")

    with pytest.raises(ValueError) as excinfo:
        _Crystalliser("CR-1", variant="draft_tube")
    message = str(excinfo.value)
    assert "belongs to whichever class draws it." in message
    assert "generic form" not in message
