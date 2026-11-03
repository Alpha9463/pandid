import os
import re
import warnings

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
    assert isinstance(w.port("inlet"), Port)
    assert w.inlet is w.ports["inlet"]
    assert w.outlet.direction == "outlet"
    assert w.inlet.owner is w


def test_unit_starts_unattached():
    w = _Widget("W-1")
    assert w.flowsheet is None


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


@pytest.mark.parametrize("bad", [-40, 0, float("nan"), float("inf"), float("-inf")])
def test_a_non_positive_or_non_finite_size_is_refused(bad):
    """Check that a non-positive or non-finite width or height is refused."""
    with pytest.raises(ValueError, match="not a usable size|finite number"):
        _Widget("W-1", width=bad)
    with pytest.raises(ValueError, match="not a usable size|finite number"):
        _Widget("W-2", height=bad)


@pytest.mark.parametrize("bad", [-5, 0, float("nan"), float("inf")])
def test_a_bad_size_assigned_later_is_refused_and_the_old_one_kept(bad):
    """Check that a bad size assigned later is refused and the old size kept."""
    w = _Widget("W-4", width=90, height=40)
    with pytest.raises(ValueError, match="not a usable size|finite number"):
        w.width = bad
    with pytest.raises(ValueError, match="not a usable size|finite number"):
        w.height = bad
    assert (w.width, w.height) == (90, 40)


def test_a_positive_size_and_none_are_both_still_accepted():
    w = _Widget("W-3", width=90, height=None)
    assert w.width == 90 and w.height is None


# --- Built-in unit types ---

from pandid import devices as D, units as U  # noqa: E402


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
    assert set(U.Separator("V").ports) == {"feed_1", "vapor", "liquid"}
    assert set(U.Column("T").ports) == {"feed_1", "overhead", "bottoms"}
    # A plain Reactor is stirred, so it has a ``drive``; ``agitator=None`` drops it.
    assert set(U.Reactor("R").ports) == {"feed_1", "outlet", "vent", "duty", "drive"}
    assert set(U.Reactor("R", agitator=None).ports) == {"feed_1", "outlet", "vent", "duty"}


def test_distillation_column_return_nozzles_close_the_internal_loops():
    col = U.DistillationColumn("T-101")
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
    """Check that a column takes a numbered family of feeds."""
    col = U.Column("T-302", n_feeds=2)
    assert set(col.ports) == {"feed_1", "feed_2", "overhead", "bottoms"}
    assert col.feed_1.direction == "inlet"
    assert col.feed_2.role == "feed"


def test_one_feed_is_numbered_and_feed_is_an_alias_for_it():
    """Check that a lone feed is ``feed_1``, the one member of ``feeds``, aliased as ``feed``."""
    for one in (U.Column("T-101"), U.Reactor("R-101"), U.Separator("V-101")):
        assert "feed_1" in one.ports
        assert "feed" not in one.ports
        assert one.feed is one.feed_1
        assert [p.name for p in one.feeds] == ["feed_1"]
        assert one.feeds[0] is one.feed


def test_a_reactor_takes_more_than_one_charge_nozzle_and_drops_the_bare_alias():
    r = U.Reactor("R-201", n_feeds=3)
    assert {"feed_1", "feed_2", "feed_3"} <= set(r.ports)
    assert "feed" not in r.ports
    assert not hasattr(r, "feed")


@pytest.mark.parametrize(
    ("build", "message"),
    [
        (lambda: U.Column("T", n_feeds=0), "Column requires at least 1 feed"),
        (lambda: U.Reactor("R", n_feeds=0), "Reactor requires at least 1 feed"),
        (lambda: U.Separator("V", n_feeds=0), "Separator requires at least 1 feed"),
        (lambda: U.Column("T", n_draws=-1), "cannot take a negative number of draws"),
        (lambda: U.Mixer("M", n_inlets=0), "at least 1 inlet"),
        (lambda: U.Splitter("S", n_outlets=0), "at least 1 outlet"),
        (
            lambda: U.Column("T-1", n_feeds=2, feed_stages=[5]),
            r"T-1 has 2 feeds \(feed_1, feed_2\) but feed_stages names 1",
        ),
        (
            lambda: U.Column("T-1", n_draws=2, draw_stages=[5]),
            r"T-1 has 2 draws \(draw_1, draw_2\) but draw_stages names 1",
        ),
        (
            lambda: U.Column("T-1", internals="tray", trays=30, feed_stages=[40]),
            "stage 40 is not on a column of 30",
        ),
        (
            lambda: U.Column("T-1", internals="tray", trays=30, n_draws=1, draw_stages=[40]),
            "stage 40 is not on a column of 30",
        ),
        (lambda: U.Column("T-1", internals=None, feed_stages=[1]), "internals is None"),
        (
            lambda: U.Column("T-1", internals=None, n_draws=1, draw_stages=[1]),
            "draw_stages names a stage",
        ),
    ],
)
def test_a_count_or_stage_the_unit_cannot_draw_is_refused(build, message):
    """Check that an impossible nozzle count or stage is refused by name."""
    with pytest.raises(ValueError, match=message):
        build()


# --- Separator: the feed family ---------------------------------------------


def test_a_separator_takes_more_than_one_feed():
    """Check that a separator takes a numbered family of feeds and drops the bare alias."""
    sep = U.Separator("V-401", n_feeds=2, characteristic="gravity")
    assert set(sep.ports) == {"feed_1", "feed_2", "overflow", "underflow"}
    assert sep.feed_1.direction == "inlet"
    assert sep.feed_2.role == "feed"
    assert [port.name for port in sep.feeds] == ["feed_1", "feed_2"]
    assert not hasattr(sep, "feed")


@pytest.mark.parametrize("characteristic", ["gravity", "electrostatic", "electromagnetic"])
def test_a_characteristic_typed_as_the_variant_is_refused(characteristic):
    """Check that a characteristic given as ``variant=`` is refused, naming the keyword."""
    with pytest.raises(ValueError, match=f"characteristic={characteristic!r}"):
        U.Separator("V-1", variant=characteristic)


@pytest.mark.parametrize(
    ("cls", "resolved"),
    [(D.GravitySeparator, "gravity"), (D.ElectrostaticPrecipitator, "electrostatic")],
)
def test_a_device_class_aliased_to_a_characteristic_still_builds(cls, resolved):
    """Check that a device class aliased to a characteristic builds and refuses it as a variant."""
    unit = cls("V-1")
    assert (unit.variant, unit.characteristic) == (resolved, resolved)
    with pytest.raises(ValueError, match="characteristic"):
        cls("V-1", variant=resolved)


@pytest.mark.parametrize(
    "variant", ["default", "knockout", "cyclone", "scrubber", "venturi_scrubber", "sifter"]
)
def test_every_separator_but_one_takes_the_family(variant):
    """Check that every separator drawing but the horizontal drum takes ``n_feeds=``."""
    sep = U.Separator("V-1", n_feeds=3, variant=variant)
    assert [port.name for port in sep.feeds] == ["feed_1", "feed_2", "feed_3"]


def test_a_horizontal_drum_refuses_a_second_feed_and_says_why():
    """Check that a horizontal drum refuses a second feed by name and keeps the ``feed`` alias."""
    with pytest.raises(ValueError, match="drawn with one feed nozzle"):
        U.Separator("V-1", n_feeds=2, variant="horizontal")
    one = U.Separator("V-2", variant="horizontal")
    assert one.feed is one.feed_1


def test_a_horizontal_drums_one_feed_still_reaches_its_three_heads():
    """Check that a horizontal drum's ``feed_1`` is offered the stencil's three ``feed`` faces."""
    from pandid.portgeom import port_faces

    drum = U.Separator("V-1", variant="horizontal")
    assert port_faces(drum, "feed_1") == port_faces(drum, "feed") == ["W", "N", "E"]


def test_a_separators_feeds_march_down_the_wall_from_where_the_one_feed_was():
    """Check that a cyclone's feeds run down the wall from where its lone feed sits."""
    from pandid.portgeom import port_offset

    lone = U.Separator("CY-1", variant="cyclone").pin(x=0, y=0)
    assert port_offset(lone, "feed") == (0.0, 12.0)

    three = U.Separator("CY-2", n_feeds=3, variant="cyclone").pin(x=0, y=0)
    assert [port_offset(three, name) for name in ("feed_1", "feed_2", "feed_3")] == [
        (0.0, 12.0),
        (0.0, 32.0),
        (0.0, 52.0),
    ]
    # The hopper starts at y = 80, so every member is on the straight wall.
    assert all(
        port_offset(three, name)[1] < 80.0 for name in three.ports if name.startswith("feed")
    )


def test_an_upright_drums_feeds_straddle_the_nozzle_the_shell_was_drawn_with():
    """Check that an upright drum's feeds straddle the mid-height point a lone feed lands on."""
    from pandid.portgeom import port_offset

    assert port_offset(U.Separator("V-1").pin(x=0, y=0), "feed") == (0.0, 50.0)
    two = U.Separator("V-2", n_feeds=2).pin(x=0, y=0)
    assert [port_offset(two, name) for name in ("feed_1", "feed_2")] == [
        (0.0, 40.0),
        (0.0, 60.0),
    ]


# --- Absorber and Stripper: a Column missing the nozzles it does not have ----


def test_absorber_has_neither_loop():
    """Check that an absorber is a column with only a feed, an overhead and a bottoms."""
    absorber = U.Absorber("V-501")
    assert set(absorber.ports) == {"feed_1", "overhead", "bottoms"}
    assert isinstance(absorber, U.Column)


def test_absorber_defaults_to_packing():
    """Check that an absorber defaults to packing and still takes other internals."""
    assert U.Absorber("V-501").internals == "packing"
    assert U.Column("T-101").internals is None
    bare = U.Absorber("V-502", internals=None)
    assert bare.internals is None
    trayed = U.Absorber("V-503", internals="valve_tray", trays=6)
    assert trayed.internals == "valve_tray" and trayed.trays == 6


def test_stripper_keeps_the_reboiler_loop_but_not_the_condenser():
    """Check that a stripper has the reboiler nozzles and not the condenser ones."""
    stripper = U.Stripper("T-601")
    assert set(stripper.ports) == {
        "feed_1",
        "overhead",
        "bottoms",
        "boilup_in",
        "reboiler_duty",
    }
    assert stripper.boilup_in.role == "vapor"
    assert stripper.reboiler_duty.role == "energy"
    assert isinstance(stripper, U.Column)
    assert stripper.internals is None


def test_absorber_and_stripper_take_more_than_one_feed():
    """Check that an absorber and a stripper take a family of feeds."""
    absorber = U.Absorber("V-501", internals="packing", trays=8, n_feeds=2, feed_stages=[1, 8])
    assert {"feed_1", "feed_2"} <= set(absorber.ports)
    assert absorber.feeds[0].name == "feed_1"

    stripper = U.Stripper("T-601", n_feeds=2)
    assert {"feed_1", "feed_2"} <= set(stripper.ports)


# --- DistillationColumn: the four nozzles a general tower does not have ------


def test_distillation_column_has_all_four_return_nozzles():
    col = U.DistillationColumn("T-101")
    assert set(col.ports) == {
        "feed_1",
        "overhead",
        "bottoms",
        "reflux_in",
        "boilup_in",
        "reboiler_duty",
        "condenser_duty",
    }
    assert isinstance(col, U.Column)


def test_a_plain_column_has_no_distillation_nozzles_and_no_distillate():
    """Check that a plain column lacks the distillation nozzles and no tower has ``distillate``."""
    col = U.Column("T-101")
    for name in ("reflux_in", "boilup_in", "reboiler_duty", "condenser_duty", "distillate"):
        with pytest.raises(AttributeError, match=name):
            getattr(col, name)
    for unit in (U.Absorber("V-1"), U.Stripper("T-2"), U.DistillationColumn("T-3")):
        with pytest.raises(AttributeError, match="distillate"):
            getattr(unit, "distillate")


def test_absorber_and_stripper_never_answer_to_the_nozzles_they_refused():
    """Check that an absorber and a stripper refuse the return nozzles they lack."""
    absorber = U.Absorber("V-501")
    for name in ("reflux_in", "boilup_in", "reboiler_duty", "condenser_duty"):
        with pytest.raises(AttributeError, match=name):
            getattr(absorber, name)

    stripper = U.Stripper("T-601")
    for name in ("reflux_in", "condenser_duty"):
        with pytest.raises(AttributeError, match=name):
            getattr(stripper, name)
    assert stripper.boilup_in.role == "vapor"
    assert stripper.reboiler_duty.role == "energy"


# --- feed_stages: a feed lands on the stage it enters ------------------------


@pytest.mark.parametrize(
    ("build", "stages"),
    [
        (
            lambda: U.Column(
                "T-1", internals="valve_tray", trays=30, n_feeds=2, feed_stages=[12, 22]
            ),
            {"feed_1": 12, "feed_2": 22},
        ),
        (lambda: U.Column("T-1", internals="tray", trays=8, feed_stages=[4]), {"feed": 4}),
        (
            lambda: U.Column(
                "T-1", internals="valve_tray", trays=30, n_draws=2, draw_stages=[8, 20]
            ),
            {"draw_1": 8, "draw_2": 20},
        ),
        (
            lambda: U.Column("T-1", internals="tray", trays=8, n_draws=1, draw_stages=[4]),
            {"draw": 4},
        ),
        (
            lambda: U.Column(
                "T-1",
                internals="valve_tray",
                trays=30,
                feed_stages=[12],
                n_draws=1,
                draw_stages=[22],
            ),
            {"feed": 12, "draw": 22},
        ),
    ],
    ids=["two feeds", "one feed", "two draws", "one draw", "a feed and a draw"],
)
def test_a_stage_moves_its_nozzle_off_the_even_spread_onto_that_tray(build, stages):
    """Check that each stated feed or draw stage puts its nozzle on that tray."""
    from pandid.portgeom import port_point

    col = build().pin(x=300, y=0)
    _flowsheet_with(col).layout()
    for port, stage in stages.items():
        _, y = port_point(col, col.frame, port)
        expected = 0.11 + (stage - 0.5) * 0.78 / col.trays
        assert (y - col.frame.y) / col.frame.h == pytest.approx(expected), port


def test_a_stage_left_null_keeps_the_even_spread():
    """Check that a feed whose stage is ``None`` keeps its evenly spread point."""
    from pandid.portgeom import port_point

    plain_fs = _flowsheet_with(
        U.Column("T-1", internals="tray", trays=8, n_feeds=2).pin(x=300, y=0)
    )
    pinned_fs = _flowsheet_with(
        U.Column("T-2", internals="tray", trays=8, n_feeds=2, feed_stages=[3, None]).pin(x=300, y=0)
    )
    plain, pinned = plain_fs.units[0], pinned_fs.units[0]
    plain_fs.layout()
    pinned_fs.layout()
    assert port_point(plain, plain.frame, "feed_2") == port_point(pinned, pinned.frame, "feed_2")
    assert port_point(plain, plain.frame, "feed_1") != port_point(pinned, pinned.frame, "feed_1")


def test_a_packed_beds_stage_lands_above_the_bed_not_through_it():
    from pandid.portgeom import port_point
    from pandid.render import iso_parts

    fs = _flowsheet_with(
        U.Column("T-1", internals="packing", trays=2, feed_stages=[2]).pin(x=300, y=0)
    )
    col = fs.units[0]
    fs.layout()
    _, y = port_point(col, col.frame, "feed")
    expected = iso_parts.stage_fraction("packing", 2, 2)
    assert (y - col.frame.y) / col.frame.h == pytest.approx(expected)


def test_feed_stages_all_null_is_fine_even_on_a_bare_shell():
    """Check that ``feed_stages`` of all ``None`` is accepted on a bare shell."""
    col = U.Column("T-1", internals=None, n_feeds=2, feed_stages=[None, None])
    assert col.feed_stages == [None, None]


def test_stages_are_none_by_default_and_unwritten():
    col = U.Column("T-1", n_feeds=2, n_draws=2)
    assert col.feed_stages is None
    assert col.draw_stages is None


# --- n_draws: a side draw, the feed family reversed ---------------------


def test_a_column_has_no_draw_by_default():
    """Check that a column has no draw unless one is asked for."""
    col = U.Column("T-101")
    assert col.draws == ()
    assert "draw" not in col.ports


def test_a_column_takes_a_side_draw():
    col = U.Column("T-301", n_draws=1)
    assert set(col.ports) == {"feed_1", "draw", "overhead", "bottoms"}
    assert col.draw.direction == "outlet"
    assert col.draw.role == "draw"


def test_a_column_takes_more_than_one_side_draw():
    col = U.Column("T-301", n_draws=2)
    assert {"draw_1", "draw_2"} <= set(col.ports)
    assert "draw" not in col.ports
    assert col.draw_1.direction == "outlet"
    assert col.draw_2.role == "draw"


def test_a_draw_lands_on_the_east_face_a_feed_never_reaches():
    """Check that a draw is placed on the east face and a feed on the west."""
    from pandid.portgeom import _drawn_placements, resolve_size

    col = U.Column("T-301", n_draws=1)
    w, h = resolve_size(col)
    assert list(_drawn_placements(col, "draw", w, h, 0, False, False)) == ["E"]
    assert list(_drawn_placements(col, "feed", w, h, 0, False, False)) == ["W"]


def _flowsheet_with(unit):
    from pandid import Flowsheet

    fs = Flowsheet("T")
    fs.add(unit)
    return fs


def test_a_kettle_reboiler_has_a_bottoms_draw():
    """Check that a kettle reboiler has a liquid bottoms outlet."""
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
    """Check that each exchanger variant names its nozzles for its two sides."""
    hx = U.HeatExchanger("E-1", variant=variant)
    expected = {f"{side}_{end}" for side in sides for end in ("in", "out")}
    assert set(hx.ports) - {"bottoms"} == expected
    for side in sides:
        assert hx.ports[f"{side}_in"].direction == "inlet"
        assert hx.ports[f"{side}_out"].direction == "outlet"


def test_a_heater_and_a_cooler_carry_their_utility_side():
    """Check that a heater's utility comes in as energy and a cooler's goes out."""
    assert U.Heater("H-1").utility_in.role == "energy"
    assert U.Cooler("C-1").utility_out.direction == "outlet"


def test_only_the_kettle_carries_the_bottoms_draw():
    """Check that a plate exchanger has no bottoms nozzle."""
    plate = U.HeatExchanger("E-1", variant="plate")
    assert "bottoms" not in plate.ports
    with pytest.raises(AttributeError, match="available ports"):
        plate.bottoms


class _CountingPorts(dict):
    """A port table that counts how often it is listed."""

    listed = 0

    def __iter__(self):
        """Count a listing, then list."""
        type(self).listed += 1
        return super().__iter__()


def test_a_probe_for_an_absent_attribute_does_not_list_the_ports():
    """Check that a missing-attribute probe does not list the ports and the shown error does."""
    pump = U.Pump("P-101")
    ports = _CountingPorts(pump.ports)
    pump.__dict__["ports"] = ports
    assert getattr(pump, "large_end", "inlet") == "inlet"
    assert not hasattr(pump, "normal_position")
    assert _CountingPorts.listed == 0
    misspelt = "dischrage"
    with pytest.raises(AttributeError) as typo:
        getattr(pump, misspelt)
    assert str(typo.value) == (
        "Pump 'P-101' has no attribute or port 'dischrage'; "
        "available ports: ['discharge', 'suction']"
    )


# The flash drum's nozzles in declaration order, written out rather than read off the class.
_FLASH_DRUM_NOZZLES = [
    ("feed_1", "inlet", "feed"),
    ("vapor", "outlet", "vapor"),
    ("liquid", "outlet", "liquid"),
]


def _nozzles(unit):
    """A unit's ports as ``(name, direction, role)``, in declaration order."""
    return [(p.name, p.direction, p.role) for p in unit.ports.values()]


@pytest.mark.parametrize(
    "variant", ["default", "horizontal", "knockout", "scrubber", "not_a_variant"]
)
def test_a_separator_that_separates_phases_names_them(variant):
    """Check that phase separators and an undeclared variant carry the flash drum's nozzles."""
    assert _nozzles(U.Separator("V-101", variant=variant)) == _FLASH_DRUM_NOZZLES


# A dust collector's nozzles in declaration order.
_COLLECTOR_NOZZLES = [
    ("feed_1", "inlet", "feed"),
    ("overflow", "outlet", "process"),
    ("underflow", "outlet", "process"),
]

#: The three drawings whose catch is dust.
_COLLECTORS = ["cyclone", "gravity", "electrostatic"]


def _separator(name, drawing):
    """A Separator drawing, asked for by ``characteristic=`` where it is one."""
    how = "characteristic" if drawing in U.Separator._CHARACTERISTICS else "variant"
    return U.Separator(name, **{how: drawing})


@pytest.mark.parametrize("variant", ["default", "horizontal", "knockout", "scrubber"])
def test_a_phase_separator_keeps_the_draws_it_always_named(variant):
    """Check that a phase separator still answers to ``vapor`` and ``liquid``."""
    sep = U.Separator("V-101", variant=variant)
    assert sep.vapor is sep.ports["vapor"]
    assert sep.port("liquid") is sep.ports["liquid"]


@pytest.mark.parametrize(
    "variant", _COLLECTORS + ["sifter", "impact", "permanent_magnet", "electromagnetic"]
)
def test_a_dust_collector_or_mechanical_separator_draws_an_overflow_and_an_underflow(variant):
    """Check that a dust collector or mechanical separator has an overflow and an underflow."""
    sep = _separator("S-1", variant)
    assert _nozzles(sep) == _COLLECTOR_NOZZLES
    with pytest.raises(AttributeError, match="available ports"):
        sep.vapor


@pytest.mark.parametrize("variant", ["sifter", "impact", "permanent_magnet", "electromagnetic"])
def test_a_mechanical_separators_nozzles_land_where_the_stencil_anchors_are(variant):
    """Check that a mechanical separator anchors its overflow high and its underflow at the apex."""
    from pandid.render.symbols import default_registry

    symbol = default_registry.get("separator", variant)
    anchors = {"electromagnetic": ("vapor", "liquid")}.get(variant, ("overflow", "underflow"))
    assert (symbol.width, symbol.height) == (80.0, 120.0)
    assert symbol.ports == dict(zip(anchors, [(80.0, 12.0), (40.0, 120.0)]))
    # The feed is a family placed by the symbol's series, its first member at (0, 12).
    (feed,) = symbol.port_series
    assert (feed.face, feed.at) == ("W", 12.0)
    assert feed.placement(0, 1, symbol.width, symbol.height) == (0.0, 12.0)
    # The overflow is level with the feed; the underflow is the hopper apex.
    high, low = anchors[0], anchors[1]
    assert symbol.ports[high][1] == feed.at
    assert symbol.ports[low][1] == symbol.height


#: The four casings that take a cake off a medium and have to get rid of it.
_CAKE_FILTERS = ["press", "belt", "rotary", "rotary_scraper"]

#: The five that hold their solids in the medium.
_CLARIFYING_FILTERS = ["default", "fixed_bed", "gas", "gas_fixed_bed", "gas_belt"]


@pytest.mark.parametrize("variant", _CAKE_FILTERS)
def test_a_filter_that_forms_a_cake_draws_the_cake_and_takes_a_wash(variant):
    """Check that a cake-forming filter has a wash inlet and a cake outlet."""
    assert _nozzles(U.Filter("F-101", variant=variant)) == [
        ("inlet", "inlet", "process"),
        ("wash_in", "inlet", "utility"),
        ("outlet", "outlet", "process"),
        ("cake", "outlet", "process"),
    ]


@pytest.mark.parametrize("variant", _CLARIFYING_FILTERS + ["not_a_variant"])
def test_a_clarifying_filter_keeps_the_two_nozzles_it_always_had(variant):
    """Check that a clarifying filter, or an undeclared variant, has only an inlet and an outlet."""
    filt = U.Filter("F-101", variant=variant)
    assert _nozzles(filt) == [
        ("inlet", "inlet", "process"),
        ("outlet", "outlet", "process"),
    ]
    with pytest.raises(AttributeError, match="available ports"):
        filt.cake


def test_an_ion_exchanger_names_its_regenerant_rather_than_borrowing_a_wash():
    """Check that an ion exchanger has a regenerant inlet and a spent regenerant outlet."""
    ix = U.Filter("F-801", variant="ion_exchange")
    assert _nozzles(ix) == [
        ("inlet", "inlet", "process"),
        ("regenerant_in", "inlet", "utility"),
        ("outlet", "outlet", "process"),
        ("spent_regenerant", "outlet", "process"),
    ]
    for borrowed in ("wash_in", "cake"):
        with pytest.raises(KeyError, match="regenerant_in"):
            ix.port(borrowed)


@pytest.mark.parametrize("variant", _CAKE_FILTERS + ["ion_exchange"])
def test_every_new_filter_nozzle_lands_somewhere_the_artwork_anchors(variant):
    """Check that every cake-filter and ion-exchanger nozzle is anchored where expected."""
    from pandid.portgeom import is_anchored
    from pandid.render.symbols import default_registry

    filt = U.Filter("F-1", variant=variant)
    symbol = default_registry.get("filter", variant)
    for name in filt.ports:
        assert is_anchored(filt, name), f"filter/{variant} does not anchor {name!r}"
    inlet_x, _ = symbol.ports["inlet"]
    into, out = (
        ("wash_in", "cake") if variant in _CAKE_FILTERS else ("regenerant_in", "spent_regenerant")
    )
    # The service inlet is at y = 0 and the outlet at the floor, both inboard of the feed.
    assert symbol.ports[into][1] == 0.0
    assert symbol.ports[out][1] == symbol.height
    assert symbol.ports[into][0] > inlet_x
    assert symbol.ports[out][0] > inlet_x


#: Every registered Dryer variant, general included.
_DRYER_VARIANTS = ["default", "general", "belt", "fluidized_bed", "shelf", "spray", "turbo"]


@pytest.mark.parametrize("variant", _DRYER_VARIANTS + ["not_a_variant"])
def test_a_drier_takes_a_heating_medium_in_and_sends_moisture_out(variant):
    """Check that every drier variant has feed, product, heating-medium and vent nozzles."""
    assert _nozzles(U.Dryer("DR-1", variant=variant)) == [
        ("feed", "inlet", "feed"),
        ("product", "outlet", "process"),
        ("heating_in", "inlet", "utility"),
        ("vent", "outlet", "vapor"),
    ]


@pytest.mark.parametrize("variant", _DRYER_VARIANTS)
def test_every_driers_gas_nozzles_land_somewhere_the_artwork_anchors(variant):
    """Check that every drier variant anchors every nozzle."""
    from pandid.portgeom import is_anchored

    dryer = U.Dryer("DR-1", variant=variant)
    for name in dryer.ports:
        assert is_anchored(dryer, name), f"dryer/{variant} does not anchor {name!r}"


def test_the_two_rotary_drums_are_piped_alike():
    """Check that the plain and scraper rotary drums share their nozzles."""
    from pandid.render.symbols import default_registry

    plain = default_registry.get("filter", "rotary")
    scraper = default_registry.get("filter", "rotary_scraper")
    assert plain.ports == scraper.ports
    assert (plain.width, scraper.width) == (50.0, 55.0)


def test_mixer_variable_inlets():
    m = U.Mixer("M", n_inlets=3)
    assert set(m.ports) == {"in_1", "in_2", "in_3", "outlet"}
    assert m.in_2.direction == "inlet"
    assert m.outlet.direction == "outlet"


def test_splitter_variable_outlets():
    s = U.Splitter("S", n_outlets=3)
    assert set(s.ports) == {"inlet", "out_1", "out_2", "out_3"}
    assert s.out_3.direction == "outlet"


def test_series_membership_is_cached_and_the_cache_answers_a_wider_family():
    """Check that the cached series membership grows when a port joins the family."""
    from pandid.render.symbols import PortSeries

    s = U.Splitter("S", n_outlets=2)
    series = PortSeries("out_", "E")  # the one Splitter's own symbol declares
    assert s._series_members(series) == {"out_1": 0, "out_2": 1}

    # The only place after __init__ that writes ``self.ports``.
    s._add_port("out_3", "outlet", "process")
    assert s._series_members(series) == {"out_1": 0, "out_2": 1, "out_3": 2}


# ---------------------------------------------------------------------------
# The families, as sequences.
# ---------------------------------------------------------------------------


def test_a_family_holds_the_very_ports_the_numbered_names_are_bound_to():
    """Check that ``inlets`` holds the very ports the numbered names are bound to, in order."""
    m = U.Mixer("M", n_inlets=3)
    assert [p.name for p in m.inlets] == ["in_1", "in_2", "in_3"]
    assert m.inlets[0] is m.in_1
    assert m.inlets[2] is m.port("in_3")
    assert all(p is m.ports[p.name] for p in m.inlets)


def test_a_family_is_indexed_from_zero_while_its_nozzles_are_numbered_from_one():
    """Check that ``inlets[0]`` is ``in_1``."""
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
    """Check that a mixer's outlet is not an inlet and a splitter's inlet is not an outlet."""
    m = U.Mixer("M", n_inlets=2)
    assert m.outlet not in m.inlets
    s = U.Splitter("S", n_outlets=2)
    assert s.inlet not in s.outlets
    assert [p.name for p in s.outlets] == ["out_1", "out_2"]


def test_a_count_worked_out_at_run_time_is_the_case_the_family_exists_for():
    """Check that a mixer takes an inlet count computed at run time."""
    streams = ["S-101", "S-102", "S-103", "S-104"]
    m = U.Mixer("M-1", n_inlets=len(streams))
    assert len(m.inlets) == len(streams)
    assert [p.direction for p in m.inlets] == ["inlet"] * 4


@pytest.mark.parametrize(
    ("build", "families"),
    [
        (lambda: U.Mixer("M", n_inlets=5), ["inlets"]),
        (lambda: U.Splitter("S", n_outlets=5), ["outlets"]),
        (lambda: U.Column("T", n_feeds=5), ["feeds"]),
        # ``feed_1`` is numbered even at the default ``n_feeds=1``.
        (lambda: U.Column("T", n_draws=5), ["draws", "feeds"]),
        (lambda: U.Column("T", n_feeds=5, n_draws=5), ["feeds", "draws"]),
        (lambda: U.Reactor("R", n_feeds=5), ["feeds"]),
        (lambda: U.Separator("V", n_feeds=5), ["feeds"]),
        (lambda: U.Block("B", inputs=5, outputs=4), ["inlets", "outlets"]),
    ],
)
def test_a_family_is_every_numbered_nozzle_at_a_count_nothing_defaults_to(build, families):
    """Check that at a count of five every numbered nozzle is a family member and vice versa."""
    unit = build()
    numbered = {name for name in unit.ports if re.search(r"_\d+$", name)}
    in_families = {port.name for family in families for port in getattr(unit, family)}
    assert in_families == numbered
    assert sum(len(getattr(unit, family)) for family in families) == len(numbered)


def test_a_multi_feed_towers_family_is_its_numbered_nozzles_top_to_bottom():
    col = U.DistillationColumn("T-302", n_feeds=3)
    assert [p.name for p in col.feeds] == ["feed_1", "feed_2", "feed_3"]
    assert col.feeds[0] is col.feed_1
    assert col.reflux_in not in col.feeds
    assert col.boilup_in not in col.feeds
    assert [p.name for p in U.Reactor("R-201", n_feeds=2).feeds] == ["feed_1", "feed_2"]


def test_a_multi_draw_towers_family_is_its_numbered_nozzles_top_to_bottom():
    # DistillationColumn has no typed ``draw_1``, so it is read through ``port()``.
    col = U.DistillationColumn("T-302", n_draws=3)
    assert [p.name for p in col.draws] == ["draw_1", "draw_2", "draw_3"]
    assert col.draws[0] is col.port("draw_1")
    assert col.reflux_in not in col.draws
    assert col.boilup_in not in col.draws
    assert col.feed not in col.draws


def test_one_draw_is_the_one_tuple_holding_the_singular_nozzle():
    col = U.Column("T-101", n_draws=1)
    assert [p.name for p in col.draws] == ["draw"]
    assert col.draws[0] is col.draw


def test_tank_is_its_own_kind():
    assert U.Tank is not U.Vessel
    assert U.Tank("T-1").kind == "tank"
    assert U.Vessel("V-1").kind == "vessel"


# ---------------------------------------------------------------------------
# A vessel's and a tank's five nozzles
# ---------------------------------------------------------------------------

#: The five nozzles both classes offer, by the name an author writes.
_HOLDUP_PORTS = ["inlet", "outlet", "vent", "relief", "drain"]


@pytest.mark.parametrize("cls", [U.Vessel, U.Tank], ids=["Vessel", "Tank"])
def test_a_vessel_and_a_tank_carry_the_same_five_nozzles(cls):
    """Check that a vessel and a tank carry the same nozzles, the fixed ones first."""
    assert list(cls("X-1").ports) == ["vent", "relief", "drain", "in_1", "out_1"]


@pytest.mark.parametrize("cls", [U.Vessel, U.Tank], ids=["Vessel", "Tank"])
def test_each_added_nozzle_leaves_the_vessel_and_says_what_it_carries(cls):
    """Check the directions and roles of a vessel's and a tank's nozzles."""
    u = cls("X-1")
    assert [u.port(n).direction for n in _HOLDUP_PORTS] == ["inlet"] + ["outlet"] * 4
    assert u.vent.role == "vapor"
    assert u.relief.role == "process"
    assert u.drain.role == "liquid"


@pytest.mark.parametrize("cls", [U.Vessel, U.Tank], ids=["Vessel", "Tank"])
def test_the_three_fixed_nozzles_are_never_numbered(cls):
    """Check that ``vent``, ``relief`` and ``drain`` are not read as a numbered family."""
    from pandid.validate import _family_stem

    assert [
        n
        for n in cls("X-1").ports
        if _family_stem(n) is not None and not n.startswith(("in_", "out_"))
    ] == []


@pytest.mark.parametrize("cls", [U.Vessel, U.Tank], ids=["Vessel", "Tank"])
def test_the_default_face_methods_are_deprecated(cls: type[U.Vessel | U.Tank]) -> None:
    """Each warns at the caller's line, is reported, and still answers the face."""
    from pandid import Flowsheet

    fs = Flowsheet("faces")
    unit = fs.add(cls("X-1"))
    with pytest.warns(DeprecationWarning, match="default_input_face") as caught:
        faces = (unit.default_input_face(), unit.default_output_face())
    assert faces == unit.input_faces + unit.output_faces
    assert {os.path.normcase(os.path.realpath(w.filename)) for w in caught} == {
        os.path.normcase(os.path.realpath(__file__))
    }
    found = [issue.message for issue in fs.validate() if issue.code == "deprecated"]
    assert found == [str(caught[0].message)]


@pytest.mark.parametrize("cls", [U.Vessel, U.Tank], ids=["Vessel", "Tank"])
def test_building_and_writing_a_vessel_raises_no_deprecation(
    cls: type[U.Vessel | U.Tank],
) -> None:
    """Construction and the spec round trip use the faces without the deprecated calls."""
    from pandid import Flowsheet

    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        fs = Flowsheet("quiet")
        fs.add(cls("X-1", inputs=2))
        Flowsheet.from_dict(fs.to_dict())


def test_fitting_is_one_class_with_device_variants():
    st = U.Fitting("ST-1", variant="strainer")
    assert st.kind == "fitting"
    assert set(st.ports) == {"inlet", "outlet"}
    assert U.Fitting("SG-1", variant="sight_glass").kind == st.kind


def test_ejector_has_three_connections():
    e = U.Ejector("EJ-1")
    assert set(e.ports) == {"motive", "suction", "discharge"}
    assert e.motive.role == "utility"
    assert e.discharge.direction == "outlet"


def test_a_cooling_tower_names_its_two_sides_and_taps_its_basin():
    ct = U.CoolingTower("CT-101")
    assert list(ct.ports) == ["water_in", "water_out", "air_in", "air_out", "makeup", "blowdown"]
    assert ct.water_in.direction == "inlet"
    assert ct.water_out.direction == "outlet"
    assert ct.makeup.role == "utility"
    assert ct.blowdown.role == "liquid"


def test_both_cooling_tower_drafts_are_piped_alike():
    drafts = [
        U.CoolingTower("CT-1", variant=v) for v in ("default", "induced_draft", "forced_draft")
    ]
    assert {tuple(ct.ports) for ct in drafts} == {tuple(drafts[0].ports)}


def test_open_ends_have_a_single_port_each_way():
    assert set(U.Vent("V-1").ports) == {"inlet"}
    assert U.Vent("V-1").inlet.direction == "inlet"
    assert set(U.Funnel("FN-1").ports) == {"outlet"}
    assert U.Funnel("FN-1").outlet.direction == "outlet"
