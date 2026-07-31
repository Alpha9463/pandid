import pytest
from pandid.units import Unit
from pandid.ports import Port


class _Widget(Unit):
    kind = "widget"
    PORTS = [("inlet", "inlet", "process"), ("outlet", "outlet", "process")]


def test_unit_declares_ports_as_dict_and_attributes():
    w = _Widget("W-1")
    assert w.name == "W-1"
    assert w.kind == "widget"
    assert set(w.ports) == {"inlet", "outlet"}
    # dict access
    assert isinstance(w.port("inlet"), Port)
    # attribute access
    assert w.inlet is w.ports["inlet"]
    assert w.outlet.direction == "outlet"
    assert w.inlet.owner is w


def test_unit_starts_unattached_with_empty_params():
    w = _Widget("W-1")
    assert w.flowsheet is None
    assert w.params == {}


def test_port_lookup_raises_helpful_error():
    w = _Widget("W-1")
    with pytest.raises(KeyError, match="no port named 'bogus'"):
        w.port("bogus")


def test_duplicate_port_name_raises():
    class _Bad(Unit):
        kind = "bad"
        PORTS = [("x", "inlet", "process"), ("x", "outlet", "process")]

    with pytest.raises(ValueError, match="already has a port named 'x'"):
        _Bad("B-1")


def test_invalid_port_role_raises():
    class _BadRole(Unit):
        kind = "badrole"
        PORTS = [("in", "inlet", "magic")]

    with pytest.raises(ValueError, match="Invalid role 'magic'"):
        _BadRole("B-2")


# --- Built-in unit types ---

from pandid import units as U  # noqa: E402


def test_fixed_port_units_have_expected_ports():
    assert set(U.Feed("F").ports) == {"outlet"}
    assert set(U.Product("P").ports) == {"inlet"}
    assert set(U.Pump("K").ports) == {"suction", "discharge"}
    assert set(U.HeatExchanger("E").ports) == {
        "shell_in",
        "shell_out",
        "tube_in",
        "tube_out",
    }
    assert set(U.Separator("V").ports) == {"feed", "vapor", "liquid"}
    assert set(U.Column("T").ports) == {
        "feed",
        "distillate",
        "bottoms",
        "reflux_in",
        "boilup_in",
        "reboiler_duty",
        "condenser_duty",
    }
    assert set(U.Reactor("R").ports) == {"feed", "outlet", "vent", "duty"}


def test_column_return_nozzles_close_the_internal_loops():
    # reflux and boilup return to the tower itself; without them a reflux loop
    # has to be faked as a recycle to an upstream unit.
    col = U.Column("T-101")
    assert col.reflux_in.direction == "inlet"
    assert col.boilup_in.direction == "inlet"
    assert col.reflux_in.role == "liquid"
    assert col.boilup_in.role == "vapor"


def test_reactor_duty_is_energy_role():
    r = U.Reactor("R")
    assert r.duty.role == "energy"
    assert r.feed.direction == "inlet"
    assert r.outlet.direction == "outlet"


def test_a_column_takes_more_than_one_feed():
    """Extractive distillation puts the solvent in above the feed tray, so a
    tower with a single nozzle cannot be drawn at all."""
    col = U.Column("T-302", n_feeds=2)
    assert set(col.ports) == {
        "feed_1",
        "feed_2",
        "distillate",
        "bottoms",
        "reflux_in",
        "boilup_in",
        "reboiler_duty",
        "condenser_duty",
    }
    assert col.feed_1.direction == "inlet"
    assert col.feed_2.role == "feed"


def test_one_feed_keeps_the_singular_name():
    """The count only changes the spelling once there is more than one of them,
    so every sheet ever drawn against ``col.feed`` still says what it meant."""
    assert "feed" in U.Column("T-101").ports
    assert "feed_1" not in U.Column("T-101").ports
    assert "feed" in U.Reactor("R-101").ports


def test_a_reactor_takes_more_than_one_charge_nozzle():
    r = U.Reactor("R-201", n_feeds=3)
    assert {"feed_1", "feed_2", "feed_3"} <= set(r.ports)
    assert "feed" not in r.ports


def test_a_unit_with_no_feed_at_all_is_rejected():
    with pytest.raises(ValueError, match="Column requires at least 1 feed"):
        U.Column("T", n_feeds=0)
    with pytest.raises(ValueError, match="Reactor requires at least 1 feed"):
        U.Reactor("R", n_feeds=0)


def test_a_kettle_reboiler_has_a_bottoms_draw():
    """What does not boil overflows the weir and leaves the plant from there,
    which is why the draw belongs on the exchanger and not on an invented
    splitter in the sump line."""
    kettle = U.HeatExchanger("E-702", variant="kettle")
    assert kettle.bottoms.direction == "outlet"
    assert kettle.bottoms.role == "liquid"


@pytest.mark.parametrize(
    "variant,sides",
    [
        ("default", ("shell", "tube")),
        ("shell_tube", ("shell", "tube")),
        ("straight_tubes", ("shell", "tube")),
        ("finned", ("shell", "tube")),
        ("condenser", ("shell", "tube")),
        ("u_tube", ("shell", "tube")),
        ("hairpin", ("shell", "tube")),
        ("double_pipe", ("shell", "tube")),
        ("kettle", ("shell", "tube")),
        ("air_cooled", ("tube", "air")),
        ("plate", ("side_a", "side_b")),
        ("spiral", ("side_a", "side_b")),
        ("thin_film", ("jacket", "product")),
    ],
)
def test_an_exchangers_nozzles_are_named_for_its_two_sides(variant, sides):
    """A nozzle names the side of the equipment it is on, not the duty crossing
    it: which fluid runs in the shell and which in the tubes is a design
    decision the drawing records, while which one is hot inverts between
    operating cases without the nozzle moving. A variant that has no shell and
    no tubes names what it does have instead."""
    hx = U.HeatExchanger("E-1", variant=variant)
    expected = {f"{side}_{end}" for side in sides for end in ("in", "out")}
    assert set(hx.ports) - {"bottoms"} == expected
    for side in sides:
        assert hx.ports[f"{side}_in"].direction == "inlet"
        assert hx.ports[f"{side}_out"].direction == "outlet"


def test_the_old_duty_names_are_gone():
    """`hot`/`cold` described the process rather than the equipment and did not
    land on the same face from one variant to the next. They are removed rather
    than aliased, and the AttributeError names the real nozzles."""
    for unit, gone in (
        (U.HeatExchanger("E-1"), "cold_in"),
        (U.Heater("H-1"), "duty"),
        (U.Cooler("C-1"), "duty"),
    ):
        with pytest.raises(AttributeError, match="available ports"):
            getattr(unit, gone)
    assert U.Heater("H-1").utility_in.role == "energy"
    assert U.Cooler("C-1").utility_out.direction == "outlet"


def test_only_the_kettle_carries_the_bottoms_draw():
    """A plate exchanger has no weir, so handing every hex the nozzle would give
    most of them one the symbol cannot place."""
    plate = U.HeatExchanger("E-1", variant="plate")
    assert "bottoms" not in plate.ports
    with pytest.raises(AttributeError, match="available ports"):
        plate.bottoms


# Exactly what 0.1.0 shipped, in order. Written out here rather than read off
# the class so the test compares against the release and not against itself.
_FLASH_DRUM_NOZZLES = [
    ("feed", "inlet", "feed"),
    ("vapor", "outlet", "vapor"),
    ("liquid", "outlet", "liquid"),
]


def _nozzles(unit):
    """A unit's ports as ``(name, direction, role)``, in declaration order."""
    return [(p.name, p.direction, p.role) for p in unit.ports.values()]


@pytest.mark.parametrize(
    "variant",
    [
        "default",
        "horizontal",
        "knockout",
        "cyclone",
        "gravity",
        "scrubber",
        "electrostatic",
    ],
)
def test_every_separator_0_1_0_could_draw_keeps_the_nozzles_it_shipped_with(variant):
    """Giving `Separator` per-variant nozzles must not move a single one of the
    nozzles it already had. These seven are every variant the symbol registry
    answered to at 0.1.0, so this list is the released API: the same names, in
    the same order, with the same directions and roles."""
    assert _nozzles(U.Separator("V-101", variant=variant)) == _FLASH_DRUM_NOZZLES


@pytest.mark.parametrize("variant", ["sifter", "impact", "permanent_magnet", "electromagnetic"])
def test_a_mechanical_separator_draws_an_overflow_and_an_underflow(variant):
    """A sifter's two products are size fractions and a magnet's are a bulk
    stream and the tramp metal pulled out of it. Neither is a vapour or a
    liquid, so neither borrows a phase it does not have. All four stencils are
    one body with a high draw and a low draw, which is what the pair names, and
    it is what classification calls them anyway."""
    sep = U.Separator("S-1", variant=variant)
    assert _nozzles(sep) == [
        ("feed", "inlet", "feed"),
        ("overflow", "outlet", "process"),
        ("underflow", "outlet", "process"),
    ]
    # And it does not also carry the drum's, which the symbol cannot place.
    with pytest.raises(AttributeError, match="available ports"):
        sep.vapor


@pytest.mark.parametrize("variant", ["sifter", "impact", "permanent_magnet", "electromagnetic"])
def test_a_mechanical_separators_nozzles_land_where_the_stencil_anchors_are(variant):
    """The names are only true if the overflow really is the high draw and the
    underflow the low one. All four share the electrostatic precipitator's body
    anchor for anchor, so the map is the same three points on every one."""
    from pandid.render.symbols import default_registry

    symbol = default_registry.get("separator", variant)
    assert (symbol.width, symbol.height) == (80.0, 120.0)
    assert symbol.ports == {
        "feed": (0.0, 12.0),
        "overflow": (80.0, 12.0),
        "underflow": (40.0, 120.0),
    }
    # The overflow is on the side wall level with the feed; the underflow is the
    # hopper apex, the lowest point the artwork has.
    assert symbol.ports["overflow"][1] == symbol.ports["feed"][1]
    assert symbol.ports["underflow"][1] == symbol.height


def test_a_separator_variant_nobody_declared_still_gets_the_flash_drums_nozzles():
    """The port table falls back rather than guessing, exactly as the
    exchanger's does. Whether the variant name is real at all is the symbol
    registry's question, asked at render."""
    assert _nozzles(U.Separator("V-9", variant="not_a_variant")) == _FLASH_DRUM_NOZZLES


def test_mixer_variable_inlets():
    m = U.Mixer("M", n_inlets=3)
    assert set(m.ports) == {"in_1", "in_2", "in_3", "outlet"}
    assert m.in_2.direction == "inlet"
    assert m.outlet.direction == "outlet"


def test_splitter_variable_outlets():
    s = U.Splitter("S", n_outlets=3)
    assert set(s.ports) == {"inlet", "out_1", "out_2", "out_3"}
    assert s.out_3.direction == "outlet"


# ---------------------------------------------------------------------------
# The families, as sequences. A count chosen at construction cannot be in the
# type, so the *family* is what a class can declare; see units.Mixer.
# ---------------------------------------------------------------------------


def test_a_family_holds_the_very_ports_the_numbered_names_are_bound_to():
    """Not copies, and not names: the same objects, in declaration order.

    Copies would be a second set of nozzles that a `connect()` writing a stream
    onto one of them would leave the other half of the sheet ignorant of.
    """
    m = U.Mixer("M", n_inlets=3)
    assert [p.name for p in m.inlets] == ["in_1", "in_2", "in_3"]
    assert m.inlets[0] is m.in_1
    assert m.inlets[2] is m.port("in_3")
    assert all(p is m.ports[p.name] for p in m.inlets)


def test_a_family_is_indexed_from_zero_while_its_nozzles_are_numbered_from_one():
    """The off-by-one worth writing down, because it is the one a reader trips on.

    `inlets` is an ordinary Python sequence and nothing re-bases it, so
    `inlets[0]` is `in_1`. Where the number is wanted it is already a name, and
    `enumerate(..., start=1)` is what recovers both at once.
    """
    m = U.Mixer("M", n_inlets=4)
    assert m.inlets[0] is m.in_1
    assert m.inlets[3] is m.in_4
    assert [(i, p.name) for i, p in enumerate(m.inlets, start=1)] == [
        (1, "in_1"),
        (2, "in_2"),
        (3, "in_3"),
        (4, "in_4"),
    ]


def test_a_family_holds_only_its_own_side():
    """A mixer's outlet is not an inlet, and a splitter's inlet is not an outlet.

    Worth a line because both spellings are one character apart from a member of
    the other family (`inlet` beside `in_1`, `outlet` beside `out_1`), which is
    exactly the sort of near-miss a prefix match gets wrong.
    """
    m = U.Mixer("M", n_inlets=2)
    assert m.outlet not in m.inlets
    s = U.Splitter("S", n_outlets=2)
    assert s.inlet not in s.outlets
    assert [p.name for p in s.outlets] == ["out_1", "out_2"]


def test_a_count_worked_out_at_run_time_is_the_case_the_family_exists_for():
    """`n_inlets=len(...)` is the call a per-arity class could never have typed.

    A literal count is the easy half; a count read off the data is what a sheet
    built from a stream table actually writes, and it is why the family is a
    sequence rather than one class per arity.
    """
    streams = ["S-101", "S-102", "S-103", "S-104"]
    m = U.Mixer("M-1", n_inlets=len(streams))
    assert len(m.inlets) == len(streams)
    assert [p.direction for p in m.inlets] == ["inlet"] * 4


def test_one_feed_is_the_one_tuple_holding_the_singular_nozzle():
    """The sequence is the general form; the singular name is not a special case.

    A one-feed tower spells its nozzle `feed`, and `feeds` is that nozzle in a
    tuple, so code written against the family reads a one-feed column and a
    three-feed column the same way and neither has to know which it got.
    """
    for one in (U.Column("T-101"), U.Reactor("R-101")):
        assert [p.name for p in one.feeds] == ["feed"]
        assert one.feeds[0] is one.feed


def test_a_multi_feed_towers_family_is_its_numbered_nozzles_top_to_bottom():
    col = U.Column("T-302", n_feeds=3)
    assert [p.name for p in col.feeds] == ["feed_1", "feed_2", "feed_3"]
    assert col.feeds[0] is col.feed_1
    # The other inlets are not charge nozzles, whatever their direction says.
    assert col.reflux_in not in col.feeds
    assert col.boilup_in not in col.feeds
    assert [p.name for p in U.Reactor("R-201", n_feeds=2).feeds] == ["feed_1", "feed_2"]


def test_tank_is_its_own_kind():
    # Tank draws its own storage-tank symbol; it is not a Vessel alias.
    assert U.Tank is not U.Vessel
    assert U.Tank("T-1").kind == "tank"
    assert U.Vessel("V-1").kind == "vessel"


def test_mixer_rejects_zero_inlets():
    with pytest.raises(ValueError, match="at least 1 inlet"):
        U.Mixer("M", n_inlets=0)


def test_splitter_rejects_zero_outlets():
    with pytest.raises(ValueError, match="at least 1 outlet"):
        U.Splitter("S", n_outlets=0)


def test_fitting_is_one_class_with_device_variants():
    # A strainer and a sight glass are the same thing to the flowsheet: two
    # faces on a line. The variant only chooses what is drawn between them.
    st = U.Fitting("ST-1", variant="strainer")
    assert st.kind == "fitting"
    assert set(st.ports) == {"inlet", "outlet"}
    assert U.Fitting("SG-1", variant="sight_glass").kind == st.kind


def test_ejector_has_three_connections():
    e = U.Ejector("EJ-1")
    assert set(e.ports) == {"motive", "suction", "discharge"}
    assert e.motive.role == "utility"
    assert e.discharge.direction == "outlet"


def test_open_ends_have_a_single_port_each_way():
    assert set(U.Vent("V-1").ports) == {"inlet"}
    assert U.Vent("V-1").inlet.direction == "inlet"
    assert set(U.Funnel("FN-1").ports) == {"outlet"}
    assert U.Funnel("FN-1").outlet.direction == "outlet"
