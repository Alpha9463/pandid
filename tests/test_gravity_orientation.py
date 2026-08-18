"""ISO 15519-1:2010 11.4.2 -- symbols where gravity is a functionality.

The clause excepts from turning any symbol for a component or device whose
function depends on gravity, and names two of them: the open tank (2061) and
the cyclone separator (X 2618), drawn at Figure 22 b). Those must not be turned.

``Symbol.gravity_fixed`` marks them and ``validate()`` reports a turned one as
``gravity-turned``. A warning rather than an error: the sheet still draws, the
nozzles still land on ink, and the only thing wrong with it is what it says
about the plant.
"""

import pytest

from pandid import Flowsheet, units as U
from pandid.render.symbols import default_registry


def _findings(fs):
    return [i for i in fs.validate() if i.code == "gravity-turned"]


def _sheet(unit, **pin):
    """One turned unit between a feed and a product, laid out and routed."""
    fs = Flowsheet("gravity")
    feed = fs.add(U.Feed("F"))
    held = fs.add(unit)
    prod = fs.add(U.Product("P"))
    if pin:
        held.pin(**pin)
    inlet = "feed" if "feed" in held.ports else "inlet"
    # Whatever the unit calls the draw gravity puts at its low point: a drum's
    # liquid, a tower's bottoms, a mechanical separator's underflow.
    outlet = next(
        name for name in ("liquid", "bottoms", "underflow", "outlet") if name in held.ports
    )
    fs.connect(feed.outlet, held.port(inlet))
    fs.connect(held.port(outlet), prod.inlet)
    fs.layout()
    fs.route()
    return fs


# --- the two symbols the clause names -----------------------------------------


def test_the_two_symbols_the_clause_names_are_marked():
    """Figure 22 b) draws exactly two: 2061 Open tank, and X 2618 Cyclone
    separator. Whatever else the registry classifies, those two have to be in
    it or the rule does not implement the clause it cites."""
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
    """A pump is installed in whatever attitude the run wants; nothing about
    the symbol is up or down, so 11.4.2's exception does not reach it."""
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
    """11.4.2 excepts *turning* only. A tank flipped left to right still stands
    the right way up, and the flip is how its nozzles reach the other side."""
    assert _findings(_sheet(U.Tank("TK-301"), x=300, y=200, mirrored=True)) == []


# --- the way out the same clause recommends -----------------------------------


def test_the_message_names_the_variant_drawn_lying_down():
    """11.4.2's own advice for a symbol that will not turn is to draw a fresh
    one in the orientation actually wanted. Two families ship one."""
    fs = _sheet(U.Vessel("D-301"), x=300, y=200, orientation=90)
    assert "variant='horizontal'" in _findings(fs)[0].message


def test_the_lying_variant_is_the_answer_and_carries_no_finding():
    fs = _sheet(U.Vessel("D-301", variant="horizontal"), x=300, y=200)
    assert _findings(fs) == []


def test_a_turned_lying_variant_is_still_reported_and_offered_no_way_out():
    """A drum already drawn lying down has no further variant to reach for, so
    the message must not send the author to the one they are using."""
    fs = _sheet(U.Vessel("D-301", variant="horizontal"), x=300, y=200, orientation=90)
    message = _findings(fs)[0].message
    assert "D-301" in message
    assert "variant=" not in message


# --- the registry-wide list ----------------------------------------------------


#: Every (kind, variant) the registry marks, and what in the artwork only means
#: one thing one way up. Written out rather than derived, so adding a symbol to
#: ``GRAVITY_FIXED`` in scripts/vendor_symbols.py is a decision this file has to
#: agree with rather than one that lands silently.
GRAVITY_FIXED = {
    # separation by density -- ISO's X 2618 and its six siblings
    ("separator", "default"),
    ("separator", "cyclone"),
    ("separator", "electrostatic"),
    ("separator", "gravity"),
    ("separator", "horizontal"),
    ("separator", "knockout"),
    ("separator", "scrubber"),
    # the venturi scrubber is fixed twice over: the family's hopper, and its own
    # throat, which the artwork draws running downward into it
    ("separator", "venturi_scrubber"),
    # the four mechanical separators, listed for the hopper rather than for what
    # does the separating: a magnet sorts by magnetism and a precipitator by
    # charge, and what fixes the attitude of all of them is the fall into the
    # hopper the artwork draws
    ("separator", "sifter"),
    ("separator", "impact"),
    ("separator", "permanent_magnet"),
    ("separator", "electromagnetic"),
    # a free liquid surface -- ISO's 2061
    ("tank", "default"),
    ("tank", "conical"),
    ("tank", "floating_roof"),
    ("tank", "sphere"),
    # ...and the three that drain to a cone rather than to a flat floor, which
    # is the hopper the mechanical separators above are listed for: turned, the
    # cone is a roof and the tank drains nowhere
    ("tank", "conical_bottom"),
    ("tank", "conical_ends"),
    ("tank", "dished_roof_conical_bottom"),
    # ...and the one whose free surface is a seal rather than the inventory: the
    # bell is drawn resting on the water, and turned it rests on nothing
    ("tank", "gas_holder"),
    # water distributed over the fill, falling through the draught into the
    # basin the artwork draws under the whole machine
    ("cooling_tower", "default"),
    ("cooling_tower", "induced_draft"),
    ("cooling_tower", "forced_draft"),
    # holdup with a vapour space over it
    ("vessel", "default"),
    ("vessel", "dished"),
    ("vessel", "dome"),
    ("vessel", "electrical_heating"),
    ("vessel", "horizontal"),
    ("vessel", "insulated"),
    ("vessel", "jacketed"),
    ("vessel", "legs"),
    ("vessel", "skirted"),
    ("vessel", "swaged"),
    # liquid running down over trays or packing, vapour rising through it
    ("column", "default"),
    ("column", "packed"),
    ("reactor", "default"),
    ("reactor", "jacketed"),
    ("reactor", "mixing"),
    ("reactor", "plain"),
    # open ends: what leaves rises, what would fall in must not
    ("vent", "default"),
    ("vent", "breather"),
    ("vent", "exhaust_head"),
    ("funnel", "default"),
    # solids that fall
    ("dryer", "spray"),
    ("dryer", "fluidized_bed"),
    # ISO group 11's thirteen rows are one trapezoid, wide at the top and
    # narrow at the bottom, with a connection tick above it and another
    # below: ore in at the mouth, product out of the throat. Turned, the
    # machine is fed from its discharge.
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
    # A machine whose purpose is to raise material: in at the boot, out at the
    # head. Turned, it lowers it. The conveyors beside it are *not* marked --
    # a belt or a screw runs whichever way the plant needs it to.
    ("elevator", "default"),
    ("elevator", "z_form"),
    # the three gas filters, each drawn with a dust hopper under its medium
    ("filter", "gas"),
    ("filter", "gas_fixed_bed"),
    ("filter", "gas_belt"),
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
    """Each of these was considered and left out; the reasons are recorded
    beside GRAVITY_FIXED in scripts/vendor_symbols.py. A conveyor is the one
    worth restating: its artwork is two rollers and a bar, symmetric top to
    bottom, so a turn makes nothing in the drawing false. The two liquid filters
    are here for the contrast with the gas casings above: the same medium drawn
    the same way, and the hopper is the only thing that fixes an attitude."""
    assert not default_registry.get(*key).gravity_fixed


def test_nothing_shipped_turns_one():
    """The examples and the golden scenarios are the drawings this package
    stands behind, so none of them may carry the finding."""
    from tests.test_golden import SCENARIOS

    offenders = []
    for name, (build, kwargs) in SCENARIOS.items():
        fs = build()
        fs.to_svg(**kwargs)
        offenders += [f"{name}: {w.message}" for w in fs.warnings if w.code == "gravity-turned"]
    assert offenders == []
