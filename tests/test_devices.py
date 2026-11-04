"""Test the generated ``pandid.devices`` classes against the generator, registry and spec."""

import re
import typing

import pytest

from pandid import Flowsheet, devices, portgeom, spec, units
from pandid.ports import Port
from pandid.render.symbols import default_registry
from test_port_annotations import view_nozzles
from test_symbol_invariants import _drawing, _script

DEVICE_CLASSES = [getattr(devices, name) for name in devices.__all__]
IDS = [cls.__name__ for cls in DEVICE_CLASSES]


# --- The generated file, against the generator that emits it ---


def test_the_committed_module_matches_the_generator():
    """Check that pandid/devices.py matches what the generator emits today."""
    generator = _script("gen_devices")
    committed = generator.OUT.read_text(encoding="utf-8")
    if generator.render() != committed:
        pytest.fail(
            "pandid/devices.py is not what scripts/gen_devices.py emits today.\n"
            "It is regenerated wholesale, so a hand edit is lost the next time\n"
            "anyone runs the generator. Change the DEVICES, OWNS or\n"
            "STAYS_ON_BASE entry that produces it, then run\n\n"
            "    python scripts/gen_devices.py\n\n"
            "and commit the regenerated file with the change that caused it.",
            pytrace=False,
        )


def test_every_registered_symbol_is_claimed_exactly_once():
    """Check that the generator claims every registered symbol exactly once."""
    claimed = _script("gen_devices").claims()
    assert claimed.keys() == set(default_registry._symbols)


def test_the_generator_refuses_a_drawing_nobody_has_classified():
    """Check that the generator refuses a registered drawing no entry classifies."""
    generator = _script("gen_devices")
    key, why = next(iter(generator.STAYS_ON_BASE.items()))
    del generator.STAYS_ON_BASE[key]
    try:
        with pytest.raises(SystemExit, match=f"{key[0]}/{key[1]}"):
            generator.claims()
    finally:
        generator.STAYS_ON_BASE[key] = why


def test_the_generator_refuses_two_claims_on_one_drawing():
    """Check that the generator refuses two claims on one drawing."""
    generator = _script("gen_devices")
    key = ("separator", "cyclone")
    generator.STAYS_ON_BASE[key] = "a second claim, for the test"
    try:
        with pytest.raises(SystemExit, match="two claims on one drawing"):
            generator.claims()
    finally:
        del generator.STAYS_ON_BASE[key]


@pytest.mark.parametrize("kind", ["instrument", "feed", "product"])
def test_the_generator_refuses_the_three_kinds_that_may_not_have_classes(kind):
    """Check that the generator refuses a class for an instrument, feed or product."""
    generator = _script("gen_devices")
    assert kind in generator.REFUSED_KINDS
    generator.DEVICES[(kind, "default")] = ("Bogus", "...")
    try:
        with pytest.raises(SystemExit, match=f"a {kind} may not have a class"):
            generator.claims()
    finally:
        del generator.DEVICES[(kind, "default")]


# --- What each class declares, against what its drawing anchors ---


@pytest.mark.parametrize("cls", DEVICE_CLASSES, ids=IDS)
def test_every_variant_a_class_owns_anchors_the_same_nozzles(cls):
    """Check that every variant of a class builds one anchored nozzle set covering ``PORTS``."""
    built = {variant: set(cls("X-1", **_drawing(cls, variant)).ports) for variant in cls.VARIANTS}
    assert len(set(map(frozenset, built.values()))) == 1
    for variant, names in built.items():
        unit = cls("X-1", **_drawing(cls, variant))
        assert {port for port, _, _ in cls.PORTS} <= names
        assert all(portgeom.is_anchored(unit, name) for name in names)


@pytest.mark.parametrize("cls", DEVICE_CLASSES, ids=IDS)
def test_every_declared_nozzle_is_visible_to_a_type_checker(cls):
    """Check that every declared nozzle has a ``Port`` type hint on the class."""
    declared = {name for name, _, _ in cls.PORTS}
    hints = typing.get_type_hints(cls)
    assert declared <= hints.keys()
    assert all(hints[name] is Port for name in declared)


def _family_device_classes():
    """Return the device classes whose base is a variable-port family."""
    generator = _script("gen_devices")
    return [cls for cls in DEVICE_CLASSES if generator.arity_family(cls.__mro__[1])]


_FAMILY_DEVICE_CLASSES = _family_device_classes()
_FAMILY_IDS = [cls.__name__ for cls in _FAMILY_DEVICE_CLASSES]


@pytest.mark.parametrize("cls", _FAMILY_DEVICE_CLASSES, ids=_FAMILY_IDS)
def test_a_generated_family_subclass_gets_its_own_exact_arity_classes(cls):
    """Check that each generated arity class declares exactly the family nozzles it builds."""
    generator = _script("gen_devices")
    keyword, member, _default, max_n = generator.arity_family(cls.__mro__[1])
    declared = view_nozzles(devices)
    for n in range(1, max_n + 1):
        name = f"{cls.__name__}{n}"
        assert name in declared, f"{name} is not defined; the overload names it"
        built = {
            port
            for port in cls("X-1", **{keyword: n}).ports
            if re.fullmatch(rf"{member}_\d+", port)
        }
        assert declared[name] == built, (
            f"{name} declares {sorted(declared[name])} but a {keyword}={n} "
            f"{cls.__name__} builds {sorted(built)}"
        )


@pytest.mark.parametrize("cls", DEVICE_CLASSES, ids=IDS)
def test_naming_a_class_alone_asks_for_that_class_s_drawing(cls):
    """Check that every class accepts ``"default"`` and resolves it to a registered drawing."""
    assert "default" in cls.VARIANTS
    assert (cls.kind, cls("X-1").variant) in default_registry._symbols


@pytest.mark.parametrize("cls", DEVICE_CLASSES, ids=IDS)
def test_a_class_refuses_a_drawing_another_device_owns(cls):
    """Check that a class refuses a variant it does not own."""
    with pytest.raises(ValueError, match="belongs to whichever class draws it"):
        cls("X-1", variant="not_a_registered_variant")


# --- One drawing, one nozzle vocabulary ---


_COLLECTORS = [
    (devices.Cyclone, "cyclone"),
    (devices.GravitySeparator, "gravity"),
    (devices.ElectrostaticPrecipitator, "electrostatic"),
]


@pytest.mark.parametrize(("cls", "variant"), _COLLECTORS, ids=lambda x: getattr(x, "__name__", x))
def test_a_collector_draws_the_same_nozzles_whichever_way_it_was_built(cls, variant):
    """Check that a collector builds the same nozzles as ``Separator`` with its variant."""
    assert set(cls("S-1").ports) == {"feed_1", "overflow", "underflow"}
    assert set(units.Separator("X-1", **_drawing(units.Separator, variant)).ports) == set(
        cls("S-3").ports
    )


@pytest.mark.parametrize(("cls", "variant"), _COLLECTORS, ids=lambda x: getattr(x, "__name__", x))
def test_a_renamed_draw_lands_where_the_drawing_puts_the_nozzle_it_renamed(cls, variant):
    """Check that a renamed draw keeps the low-level faces and maps to the artwork's anchor."""
    renamed = cls("S-1")
    low_level = units.Separator("X-1", **_drawing(units.Separator, variant))
    symbol = default_registry.for_unit(renamed)
    for new, old in (("overflow", "vapor"), ("underflow", "liquid")):
        assert portgeom.port_faces(renamed, new) == portgeom.port_faces(low_level, new)
        assert renamed._symbol_anchor(new) == old
        assert old in symbol.ports


# --- pandid.spec round trips ---


@pytest.mark.parametrize("cls", DEVICE_CLASSES, ids=IDS)
def test_a_device_round_trips_through_a_spec(cls):
    """Check that a sheet built from each device class round-trips through a spec."""
    sheet = Flowsheet("round trip")
    original = sheet.add(cls("X-1"))
    written = sheet.to_dict()
    read_back = Flowsheet.from_dict(written)

    rebuilt = read_back.units[0]
    assert type(rebuilt) is cls
    assert rebuilt.variant == original.variant
    assert list(rebuilt.ports) == list(original.ports)
    assert read_back.to_dict() == written


def test_a_spec_may_name_a_device_class_in_either_spelling():
    """Check that a spec accepts a device class name in CamelCase, snake_case or upper case."""
    for written in ("KettleReboiler", "kettle_reboiler", "KETTLEREBOILER"):
        sheet = Flowsheet.from_dict({"name": "s", "units": [{"kind": written, "name": "E-1"}]})
        assert type(sheet.units[0]) is devices.KettleReboiler


def test_a_kind_tag_still_names_the_class_that_owns_the_whole_kind():
    """Check that each ``kind`` tag aliases the ``units`` class that owns the whole kind."""
    # Share their kind with Column.
    shares_a_kind = {"Absorber", "Stripper", "DistillationColumn"}
    for name in units.__all__:
        if name == "Unit" or name in shares_a_kind:
            continue
        base = getattr(units, name)
        assert spec._ALIASES[base.kind] == name


def test_a_device_class_takes_the_arguments_its_base_declares():
    """Check that a spec passes each device class the arguments its base declares."""
    sheet = Flowsheet.from_dict(
        {
            "name": "s",
            "units": [
                {"kind": "ControlValve", "name": "FV-101", "fail": "closed"},
                {"kind": "SpectacleBlind", "name": "SB-101", "normal_position": "closed"},
                {"kind": "StirredTankReactor", "name": "R-101", "n_feeds": 2},
            ],
        }
    )
    valve, blind, reactor = sheet.units
    assert valve.fail == "closed"
    assert blind.normal_position == "closed"
    assert {"feed_1", "feed_2"} <= set(reactor.ports)
    assert Flowsheet.from_dict(sheet.to_dict()).to_dict() == sheet.to_dict()


def test_an_instrument_is_still_refused_in_the_units_section():
    """Check that no device class is an instrument and a spec refuses one in ``units``."""
    assert not any(getattr(devices, name).kind == "instrument" for name in devices.__all__)
    with pytest.raises(spec.SpecError, match="instruments go in the top-level"):
        Flowsheet.from_dict({"name": "s", "units": [{"kind": "Instrument", "name": "FT-1"}]})


# --- The layer as API ---


def test_every_device_class_is_on_the_package():
    """Check that every device class is exported from ``pandid`` as the same object."""
    import pandid

    for name in devices.__all__:
        assert getattr(pandid, name) is getattr(devices, name)
        assert name in pandid.__all__


def test_no_device_class_shadows_a_unit_class():
    """Check that no device class name is also a ``units`` class name."""
    assert set(devices.__all__).isdisjoint(units.__all__)


@pytest.mark.parametrize("cls", DEVICE_CLASSES, ids=IDS)
def test_every_device_is_a_subclass_of_the_class_that_owns_its_kind(cls):
    """Check that every device subclasses the ``units`` class that owns its kind."""
    base = next(
        getattr(units, name)
        for name in units.__all__
        if name != "Unit"
        and getattr(units, name).kind == cls.kind
        and not getattr(units, name).VARIANTS
    )
    assert issubclass(cls, base)
    assert cls.kind == base.kind
