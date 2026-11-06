"""Check the ``gravity-turned`` warning for symbols ISO 15519-1:2010 11.4.2 keeps upright."""

import pytest

from pandid import Flowsheet, units as U
from pandid.render.symbols import default_registry


def _findings(fs):
    return [i for i in fs.validate() if i.code == "gravity-turned"]


def _has_port(unit, name):
    """Return whether ``unit`` has port ``name`` or a live alias for it."""
    return unit._canonical_port_name(name) in unit.ports


def _sheet(unit, **pin):
    """One turned unit between a feed and a product, laid out and routed."""
    fs = Flowsheet("gravity")
    feed = fs.add(U.Feed("F"))
    held = fs.add(unit)
    prod = fs.add(U.Product("P"))
    if pin:
        held.pin(**pin)
    inlet = "feed" if _has_port(held, "feed") else "inlet"
    # Whatever the unit calls the draw gravity puts at its low point: a drum's
    # liquid, a tower's bottoms, a mechanical separator's underflow.
    outlet = next(
        name for name in ("liquid", "bottoms", "underflow", "outlet") if _has_port(held, name)
    )
    fs.connect(feed.outlet, held.port(inlet))
    fs.connect(held.port(outlet), prod.inlet)
    fs.layout()
    fs.route()
    return fs


# --- the two symbols the clause names -----------------------------------------


def test_the_two_symbols_the_clause_names_are_marked():
    """Check that the open tank and the cyclone separator are marked gravity-fixed."""
    assert default_registry.get("tank").gravity_fixed
    assert default_registry.get("separator", "cyclone").gravity_fixed


# --- the finding ---------------------------------------------------------------


@pytest.mark.parametrize("turn", [90, 180, 270])
def test_a_turned_tank_is_reported(turn):
    fs = _sheet(U.Tank("TK-301"), x=300, y=200, orientation=turn)
    found = _findings(fs)
    assert [i.severity for i in found] == ["warning"]
    assert "TK-301" in found[0].message
    assert f"turned {turn}" in found[0].message
    assert "11.4.2" in found[0].message


def test_an_upright_tank_is_not_reported():
    assert _findings(_sheet(U.Tank("TK-301"), x=300, y=200)) == []


def test_the_drawing_is_still_produced():
    """A warning, not an error: to_svg() collects it and draws the sheet."""
    fs = _sheet(U.Tank("TK-301"), x=300, y=200, orientation=90)
    svg = fs.to_svg()
    assert "<svg" in svg
    assert [w.code for w in fs.warnings if w.code == "gravity-turned"] == ["gravity-turned"]


def test_one_finding_per_unit_however_many_ways_it_is_placed():
    """pin() is cumulative, so a unit nudged twice is still one turned tank."""
    tank = U.Tank("TK-301")
    fs = _sheet(tank, x=300, y=200, orientation=90)
    tank.pin(y=240)
    fs.layout()
    fs.route()
    assert len(_findings(fs)) == 1


def test_a_turned_pump_is_not_reported():
    """Check that a turned pump is not reported."""
    fs = Flowsheet("turned pump")
    feed = fs.add(U.Feed("F"))
    pump = fs.add(U.Pump("P-101")).pin(x=300, y=200, orientation=90)
    prod = fs.add(U.Product("P"))
    fs.connect(feed.outlet, pump.suction)
    fs.connect(pump.discharge, prod.inlet)
    fs.layout()
    fs.route()
    assert _findings(fs) == []


def test_mirroring_is_left_alone():
    """Check that a mirrored tank is not reported."""
    assert _findings(_sheet(U.Tank("TK-301"), x=300, y=200, mirrored=True)) == []


# --- the way out the same clause recommends -----------------------------------


def test_the_message_names_the_variant_drawn_lying_down():
    """Check that the warning names the variant drawn lying down."""
    fs = _sheet(U.Vessel("D-301"), x=300, y=200, orientation=90)
    assert "variant='horizontal'" in _findings(fs)[0].message


def test_the_lying_variant_is_the_answer_and_carries_no_finding():
    fs = _sheet(U.Vessel("D-301", variant="horizontal"), x=300, y=200)
    assert _findings(fs) == []


def test_a_turned_lying_variant_is_still_reported_and_offered_no_way_out():
    """Check that a turned lying variant is reported without being offered itself."""
    fs = _sheet(U.Vessel("D-301", variant="horizontal"), x=300, y=200, orientation=90)
    message = _findings(fs)[0].message
    assert "D-301" in message
    assert "variant=" not in message


# --- the registry-wide list ----------------------------------------------------


#: Every (kind, variant) the registry marks gravity-fixed.
GRAVITY_FIXED = {
    ("separator", "default"),
    ("separator", "cyclone"),
    ("separator", "electrostatic"),
    ("separator", "gravity"),
    ("separator", "horizontal"),
    ("separator", "knockout"),
    ("separator", "scrubber"),
    ("separator", "venturi_scrubber"),
    ("separator", "sifter"),
    ("separator", "impact"),
    ("separator", "permanent_magnet"),
    ("separator", "electromagnetic"),
    ("tank", "default"),
    ("tank", "conical"),
    ("tank", "floating_roof"),
    ("tank", "sphere"),
    ("tank", "conical_bottom"),
    ("tank", "conical_ends"),
    ("tank", "dished_roof_conical_bottom"),
    ("tank", "gas_holder"),
    ("cooling_tower", "default"),
    ("cooling_tower", "induced_draft"),
    ("cooling_tower", "forced_draft"),
    ("cooling_tower", "general"),
    ("cooling_tower", "dry_natural"),
    ("cooling_tower", "dry_forced"),
    ("cooling_tower", "dry_induced"),
    ("cooling_tower", "wet_natural"),
    ("cooling_tower", "wet_forced"),
    ("cooling_tower", "wet_induced"),
    ("cooling_tower", "wet_dry_natural"),
    ("boiler", "default"),
    ("vessel", "default"),
    ("vessel", "dished"),
    ("vessel", "dome"),
    ("vessel", "electrical_heating"),
    ("vessel", "horizontal"),
    ("vessel", "insulated"),
    ("vessel", "jacketed"),
    ("vessel", "swaged"),
    ("column", "default"),
    ("column", "packed"),
    ("reactor", "default"),
    ("reactor", "jacketed"),
    ("vent", "default"),
    ("vent", "breather"),
    ("vent", "exhaust_head"),
    ("funnel", "default"),
    ("stack", "default"),
    ("flare", "default"),
    ("dryer", "spray"),
    ("dryer", "fluidized_bed"),
    ("dryer", "shelf"),
    ("crushing_machine", "default"),
    ("crusher", "default"),
    ("crusher", "cone"),
    ("crusher", "hammer"),
    ("crusher", "impact"),
    ("crusher", "jaw"),
    ("crusher", "roller"),
    ("mill", "default"),
    ("mill", "hammer"),
    ("mill", "impact"),
    ("mill", "roller"),
    ("mill", "vibration"),
    ("elevator", "default"),
    ("elevator", "z_form"),
    ("filter", "gas"),
    ("filter", "gas_fixed_bed"),
    ("filter", "gas_belt"),
    ("feeder", "general"),
    ("feeder", "rotary_valve"),
    ("feeder", "rotary_table"),
    ("feeder", "metering"),
    ("kneader", "default"),
    ("screening_device", "general"),
    ("screening_device", "coarse_rake"),
    ("screening_device", "fine_rake"),
    ("screening_device", "coarse_and_fine"),
    ("screening_device", "vibrating"),
    ("screening_device", "rotating_drum"),
    ("screening_device", "basket_reel"),
    ("evaporator", "default"),
    ("evaporator", "calandria"),
    ("evaporator", "climbing_film"),
    ("evaporator", "falling_film"),
    ("evaporator", "plate"),
    ("crystallizer", "default"),
    ("kiln", "default"),
    ("kiln", "fluidized_bed"),
    ("kiln", "shaft"),
    ("thickener", "default"),
    ("silo", "default"),
    ("silo", "bunker"),
    ("flotation_cell", "default"),
    ("deaerator", "default"),
}


def test_the_registry_marks_exactly_that_list():
    marked = {key for key, symbol in default_registry._symbols.items() if symbol.gravity_fixed}
    assert marked == GRAVITY_FIXED


@pytest.mark.parametrize(
    "key",
    sorted(
        {
            ("hex", "kettle"),
            ("valve", "bleed"),
            ("conveyor", "default"),
            ("dryer", "default"),
            ("filter", "default"),
            ("filter", "fixed_bed"),
            ("filter", "belt"),
            ("fitting", "rotameter"),
            ("pump", "default"),
            ("mixer", "default"),
        }
    ),
)
def test_the_deliberate_exclusions_stay_turnable(key):
    """Check that each deliberately excluded symbol stays turnable."""
    assert not default_registry.get(*key).gravity_fixed
