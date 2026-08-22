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


@pytest.mark.parametrize("bad", [-40, 0, float("nan"), float("inf"), float("-inf")])
def test_a_non_positive_or_non_finite_size_is_refused(bad):
    """A box is drawn into ``<use width=... height=...>``, and the SVG spec
    calls a negative value there an error: a conformant reader draws
    nothing for it, silently, while the tag and the pipe routed to its
    nozzle are drawn as if the symbol were still there. Zero is the same
    fault by a different route -- nothing is left to draw a nozzle onto.
    """
    with pytest.raises(ValueError, match="not a usable size"):
        _Widget("W-1", width=bad)
    with pytest.raises(ValueError, match="not a usable size"):
        _Widget("W-2", height=bad)


def test_a_positive_size_and_none_are_both_still_accepted():
    w = _Widget("W-3", width=90, height=None)
    assert w.width == 90 and w.height is None


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
    assert set(U.Column("T").ports) == {"feed_1", "overhead", "bottoms"}
    assert set(U.DistillationColumn("T").ports) == {
        "feed_1",
        "overhead",
        "bottoms",
        "reflux_in",
        "boilup_in",
        "reboiler_duty",
        "condenser_duty",
    }
    # ``drive`` is the agitator's, and a plain Reactor is a stirred tank, so it
    # has one. ``Reactor("R", agitator=None)`` is the bare shell's four.
    assert set(U.Reactor("R").ports) == {"feed_1", "outlet", "vent", "duty", "drive"}
    assert set(U.Reactor("R", agitator=None).ports) == {"feed_1", "outlet", "vent", "duty"}


def test_distillation_column_return_nozzles_close_the_internal_loops():
    # reflux and boilup return to the tower itself; without them a reflux loop
    # has to be faked as a recycle to an upstream unit.
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
    """Extractive distillation puts the solvent in above the feed tray, so a
    tower with a single nozzle cannot be drawn at all."""
    col = U.Column("T-302", n_feeds=2)
    assert set(col.ports) == {"feed_1", "feed_2", "overhead", "bottoms"}
    assert col.feed_1.direction == "inlet"
    assert col.feed_2.role == "feed"


def test_one_feed_is_numbered_and_feed_is_an_alias_for_it():
    """A family of one is spelled the way ``Mixer``'s ``in_1`` always was:
    ``feed_1`` is a real nozzle whatever the count, so it does not
    disappear the moment ``n_feeds`` is raised past one, and it exists at
    one where it never used to. ``feed`` is the bare alias for it -- not a
    second port, the same object -- kept because it is the common case and
    every sheet ever drawn against ``col.feed`` still says what it meant."""
    for one in (U.Column("T-101"), U.Reactor("R-101")):
        assert "feed_1" in one.ports
        assert "feed" not in one.ports
        assert one.feed is one.feed_1


def test_a_second_feed_drops_the_bare_alias():
    """Raising ``n_feeds`` past one is what used to silently break every
    ``.feed`` reference in a file; ``.feed_1`` now survives the raise
    unchanged, and only the alias -- which never named a member once
    there was more than one -- goes."""
    r = U.Reactor("R-201", n_feeds=2)
    assert "feed_1" in r.ports
    assert not hasattr(r, "feed")


def test_a_reactor_takes_more_than_one_charge_nozzle():
    r = U.Reactor("R-201", n_feeds=3)
    assert {"feed_1", "feed_2", "feed_3"} <= set(r.ports)
    assert "feed" not in r.ports


def test_a_unit_with_no_feed_at_all_is_rejected():
    with pytest.raises(ValueError, match="Column requires at least 1 feed"):
        U.Column("T", n_feeds=0)
    with pytest.raises(ValueError, match="Reactor requires at least 1 feed"):
        U.Reactor("R", n_feeds=0)


# --- Absorber and Stripper: a Column missing the nozzles it does not have ----


def test_absorber_has_neither_loop():
    """No reboiler, no condenser, no reflux, no boilup: nothing in an
    absorber boils, so none of DistillationColumn's four return nozzles
    belongs on it."""
    absorber = U.Absorber("V-501")
    assert set(absorber.ports) == {"feed_1", "overhead", "bottoms"}
    assert isinstance(absorber, U.Column)


def test_absorber_defaults_to_packing():
    """Absorbers come packed, trayed or as a bare spray tower more often than
    a distillation column comes bare, so the default differs from Column's."""
    assert U.Absorber("V-501").internals == "packing"
    assert U.Column("T-101").internals is None
    # The knob is still Column's own: nothing about Absorber narrows it away.
    bare = U.Absorber("V-502", internals=None)
    assert bare.internals is None
    trayed = U.Absorber("V-503", internals="valve_tray", trays=6)
    assert trayed.internals == "valve_tray" and trayed.trays == 6


def test_stripper_keeps_the_reboiler_loop_but_not_the_condenser():
    """A stripper still reboils, so boilup_in and reboiler_duty stay; it
    never refluxes, so reflux_in and condenser_duty do not."""
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
    # Unlike Absorber, Stripper states no default of its own.
    assert stripper.internals is None


def test_absorber_and_stripper_take_more_than_one_feed():
    """The two counter-current inlets a real absorber has -- gas at the
    bottom, lean solvent at the top -- are the same n_feeds/feed_stages a
    Column places any other feed with; nothing about the reduced port set
    touches that machinery."""
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


def test_a_plain_column_still_answers_to_the_four_retired_nozzles():
    """#400: the type moved, and the runtime spelling still works for one
    release, warning towards the class that now really has it.

    Read through ``getattr``, not the literal attribute: a plain ``Column``
    is typed without these four now, on purpose, so the literal spelling is
    the pyright error #400 exists to make real -- see the acceptance check
    in the issue itself. This test is about the run-time promise, which
    ``getattr`` exercises exactly the same way.
    """
    col = U.Column("T-101")
    with pytest.warns(DeprecationWarning, match="DistillationColumn"):
        reflux = getattr(col, "reflux_in")
    assert reflux.direction == "inlet" and reflux.role == "liquid"
    with pytest.warns(DeprecationWarning, match="DistillationColumn"):
        boilup = getattr(col, "boilup_in")
    assert boilup.direction == "inlet" and boilup.role == "vapor"
    with pytest.warns(DeprecationWarning, match="DistillationColumn"):
        assert getattr(col, "reboiler_duty").role == "energy"
    with pytest.warns(DeprecationWarning, match="DistillationColumn"):
        assert getattr(col, "condenser_duty").role == "energy"
    # Minted once: a second read is the same object and warns no further.
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert getattr(col, "reflux_in") is reflux
    assert {"reflux_in", "boilup_in", "reboiler_duty", "condenser_duty"} <= set(col.ports)


def test_a_retired_nozzle_can_still_be_connected():
    """Not just an attribute that resolves -- a real, connectable port, so
    an existing sheet's reflux loop still draws."""
    from pandid import Flowsheet

    fs = Flowsheet("legacy")
    col = fs.add(U.Column("T-101"))
    drum = fs.add(U.Vessel("D-101"))
    with pytest.warns(DeprecationWarning):
        fs.connect(drum.outlet, getattr(col, "reflux_in"), draw_as_recycle=True)
    assert col.port("reflux_in").stream is not None


def test_distillate_still_works_everywhere_it_used_to():
    """The rename applies uniformly: Column, Absorber, Stripper and
    DistillationColumn all still answer to the retired name."""
    for unit in (
        U.Column("T-1"),
        U.Absorber("V-1"),
        U.Stripper("T-2"),
        U.DistillationColumn("T-3"),
    ):
        with pytest.warns(DeprecationWarning, match="overhead"):
            assert getattr(unit, "distillate") is unit.overhead


def test_absorber_and_stripper_never_answer_to_the_nozzles_they_refused():
    """Unlike Column, Absorber/Stripper never carried these honestly (#398),
    so they get no deprecation grace period for them either -- accessing
    one is still a hard, immediate error."""
    absorber = U.Absorber("V-501")
    for name in ("reflux_in", "boilup_in", "reboiler_duty", "condenser_duty"):
        with pytest.raises(AttributeError, match=name):
            getattr(absorber, name)

    stripper = U.Stripper("T-601")
    for name in ("reflux_in", "condenser_duty"):
        with pytest.raises(AttributeError, match=name):
            getattr(stripper, name)
    # The two it really has are not touched by any of this.
    assert stripper.boilup_in.role == "vapor"
    assert stripper.reboiler_duty.role == "energy"


# --- feed_stages: a feed lands on the stage it enters ------------------------


def test_a_feed_stage_moves_the_nozzle_off_the_even_spread():
    """The whole point: two feeds asked for different stages land at
    different, specific elevations rather than the two points the even
    spread would have put them at."""
    from pandid.portgeom import port_point

    fs = _flowsheet_with(
        U.Column("T-101", internals="valve_tray", trays=30, n_feeds=2, feed_stages=[12, 22]).pin(
            x=300, y=0
        )
    )
    col = fs.units[0]
    fs.layout()
    _, y1 = port_point(col, col.frame, "feed_1")
    _, y2 = port_point(col, col.frame, "feed_2")
    top = col.frame.y
    height = col.frame.h
    assert (y1 - top) / height == pytest.approx(0.11 + 11.5 * 0.78 / 30)
    assert (y2 - top) / height == pytest.approx(0.11 + 21.5 * 0.78 / 30)


def test_a_single_feed_column_can_pin_its_lone_nozzle_too():
    """``feed_stages=`` is not only for a multi-feed tower: a one-feed
    column's ``feed`` is a family of one, and pinning it is the same
    keyword rather than a second one for the singular case."""
    from pandid.portgeom import port_point

    fs = _flowsheet_with(
        U.Column("T-1", internals="tray", trays=8, feed_stages=[4]).pin(x=300, y=0)
    )
    col = fs.units[0]
    fs.layout()
    _, y = port_point(col, col.frame, "feed")
    assert (y - col.frame.y) / col.frame.h == pytest.approx(0.11 + 3.5 * 0.78 / 8)


def test_a_stage_left_null_keeps_the_even_spread():
    """One feed pinned and the other not: the pinned one moves, and the
    other keeps exactly the point the even spread always gave it."""
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


def test_feed_stages_length_must_match_the_feeds():
    with pytest.raises(
        ValueError,
        match=r"T-1 has 2 feeds \(feed_1, feed_2\) but "
        r"feed_stages names 1",
    ):
        U.Column("T-1", n_feeds=2, feed_stages=[5])


def test_a_stage_out_of_range_names_the_tray_count():
    with pytest.raises(ValueError, match=r"stage 40 is not on a column of 30"):
        U.Column("T-1", internals="tray", trays=30, feed_stages=[40])


def test_feed_stages_on_a_bare_shell_is_refused():
    """A bare shell has no stages, so a stage number would name a tray
    line no reader can find on the drawing."""
    with pytest.raises(ValueError, match="internals is None"):
        U.Column("T-1", internals=None, feed_stages=[1])


def test_feed_stages_all_null_is_fine_even_on_a_bare_shell():
    """Every entry left ``None`` asks nothing of the shell, so it is not
    the same request as naming a real stage."""
    col = U.Column("T-1", internals=None, n_feeds=2, feed_stages=[None, None])
    assert col.feed_stages == [None, None]


def test_feed_stages_is_none_by_default_and_unwritten():
    col = U.Column("T-1", n_feeds=2)
    assert col.feed_stages is None


# --- n_draws: a side draw, the feed family reversed ---------------------


def test_a_column_has_no_draw_by_default():
    """Most columns have none, unlike ``n_feeds``: a plain two-product
    tower gets no third nozzle it never asked for."""
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


def test_a_negative_draw_count_is_rejected():
    with pytest.raises(ValueError, match="cannot take a negative number of draws"):
        U.Column("T", n_draws=-1)


def test_a_draw_lands_on_the_east_face_a_feed_never_reaches():
    """A draw is a feed's flow reversed: it leaves opposite the wall a
    feed enters on."""
    from pandid.portgeom import _drawn_placements, resolve_size

    col = U.Column("T-301", n_draws=1)
    w, h = resolve_size(col)
    assert list(_drawn_placements(col, "draw", w, h, 0, False, False)) == ["E"]
    assert list(_drawn_placements(col, "feed", w, h, 0, False, False)) == ["W"]


# --- draw_stages: a draw lands on the stage it actually leaves from ------


def test_a_draw_stage_moves_the_nozzle_off_the_even_spread():
    from pandid.portgeom import port_point

    fs = _flowsheet_with(
        U.Column("T-301", internals="valve_tray", trays=30, n_draws=2, draw_stages=[8, 20]).pin(
            x=300, y=0
        )
    )
    col = fs.units[0]
    fs.layout()
    _, y1 = port_point(col, col.frame, "draw_1")
    _, y2 = port_point(col, col.frame, "draw_2")
    top = col.frame.y
    height = col.frame.h
    assert (y1 - top) / height == pytest.approx(0.11 + 7.5 * 0.78 / 30)
    assert (y2 - top) / height == pytest.approx(0.11 + 19.5 * 0.78 / 30)


def test_a_single_draw_column_can_pin_its_lone_nozzle_too():
    """``draw_stages=`` on a one-draw tower pins the singular ``draw``,
    the same shape ``feed_stages=`` takes on a one-feed tower."""
    from pandid.portgeom import port_point

    fs = _flowsheet_with(
        U.Column("T-1", internals="tray", trays=8, n_draws=1, draw_stages=[4]).pin(x=300, y=0)
    )
    col = fs.units[0]
    fs.layout()
    _, y = port_point(col, col.frame, "draw")
    assert (y - col.frame.y) / col.frame.h == pytest.approx(0.11 + 3.5 * 0.78 / 8)


def test_draw_stages_length_must_match_the_draws():
    with pytest.raises(
        ValueError,
        match=r"T-1 has 2 draws \(draw_1, draw_2\) but draw_stages names 1",
    ):
        U.Column("T-1", n_draws=2, draw_stages=[5])


def test_a_draw_stage_out_of_range_names_the_tray_count():
    with pytest.raises(ValueError, match=r"stage 40 is not on a column of 30"):
        U.Column("T-1", internals="tray", trays=30, n_draws=1, draw_stages=[40])


def test_draw_stages_on_a_bare_shell_is_refused():
    with pytest.raises(ValueError, match="draw_stages names a stage"):
        U.Column("T-1", internals=None, n_draws=1, draw_stages=[1])


def test_draw_stages_is_none_by_default_and_unwritten():
    col = U.Column("T-1", n_draws=2)
    assert col.draw_stages is None


def test_a_feed_stage_and_a_draw_stage_pin_independently():
    """The two stage lists are read into one merged fraction table; this
    is the check that neither keyword shadows the other's nozzle."""
    from pandid.portgeom import port_point

    fs = _flowsheet_with(
        U.Column(
            "T-101",
            internals="valve_tray",
            trays=30,
            n_feeds=1,
            feed_stages=[12],
            n_draws=1,
            draw_stages=[22],
        ).pin(x=300, y=0)
    )
    col = fs.units[0]
    fs.layout()
    _, feed_y = port_point(col, col.frame, "feed")
    _, draw_y = port_point(col, col.frame, "draw")
    top, height = col.frame.y, col.frame.h
    assert (feed_y - top) / height == pytest.approx(0.11 + 11.5 * 0.78 / 30)
    assert (draw_y - top) / height == pytest.approx(0.11 + 21.5 * 0.78 / 30)


def _flowsheet_with(unit):
    from pandid import Flowsheet

    fs = Flowsheet("T")
    fs.add(unit)
    return fs


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


@pytest.mark.parametrize("variant", ["default", "horizontal", "knockout", "scrubber"])
def test_a_separator_that_separates_phases_names_them(variant):
    """The four whose two draws really are a vapour and a liquid.

    Three drawings of a drum, where the vapour disengages off the top and the
    liquid settles out of the bottom, and the wet scrubber, whose products are a
    cleaned gas and a dirty scrubbing liquid. The list is written out rather
    than read off the class, so this compares against the released API and not
    against itself: same names, same order, same directions, same roles.
    """
    assert _nozzles(U.Separator("V-101", variant=variant)) == _FLASH_DRUM_NOZZLES


# The renamed pair, written out for the same reason ``_FLASH_DRUM_NOZZLES`` is.
_COLLECTOR_NOZZLES = [
    ("feed", "inlet", "feed"),
    ("overflow", "outlet", "process"),
    ("underflow", "outlet", "process"),
]

#: The three drawings whose catch is dust. 0.1.0 called it ``liquid`` here while
#: ``pandid.devices`` called it ``underflow`` over the same three symbols; 0.1.2
#: is where the low-level form stopped disagreeing.
_COLLECTORS = ["cyclone", "gravity", "electrostatic"]


@pytest.mark.parametrize("variant", _COLLECTORS)
def test_a_separator_that_collects_dust_draws_an_overflow_and_an_underflow(variant):
    """A hopper full of dust is not a liquid, and a precipitator's stack gas is
    not the vapour of anything. Both draws take the ``process`` role for it: the
    role vocabulary has no word for tramp metal or a size fraction, and no
    drawing reads a role that is not ``signal``."""
    assert _nozzles(U.Separator("V-101", variant=variant)) == _COLLECTOR_NOZZLES


@pytest.mark.parametrize("variant", _COLLECTORS)
@pytest.mark.parametrize("removed", ["vapor", "liquid"])
def test_a_collectors_old_draw_name_no_longer_reaches_a_nozzle(variant, removed):
    """The old pair was read for 0.1.2 and is gone in 0.1.3.

    Every by-name way in, because a sheet written at 0.1.1 used whichever it
    liked, and each answers the way it answers any other name the unit has not
    got: the nozzle list, and nothing about a deprecation.
    """
    sep = U.Separator("CY-401", variant=variant)
    with pytest.raises(AttributeError, match="overflow"):
        getattr(sep, removed)
    with pytest.raises(KeyError, match="overflow"):
        sep.port(removed)
    with pytest.raises(KeyError, match="overflow"):
        sep.nozzle(removed, "N")
    with pytest.raises(KeyError, match="overflow"):
        sep.pin(port=removed, x=300, y=400)


@pytest.mark.parametrize("variant", ["default", "horizontal", "knockout", "scrubber"])
def test_a_phase_separator_keeps_the_draws_it_always_named(variant):
    """The half of the retirement that would be easy to get wrong.

    A flash drum's ``vapor`` is the vapour leaving it. Retiring the name on the
    class rather than on the three drawings that misused it would have taken
    the correct vocabulary with the wrong one.
    """
    sep = U.Separator("V-101", variant=variant)
    assert sep.vapor is sep.ports["vapor"]
    assert sep.port("liquid") is sep.ports["liquid"]


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
    underflow the low one. All four are ISO 10628-2's separating vessel, anchor
    for anchor, so the map is the same three points on every one.

    Three of the four are still that vessel as draw.io vendored it. The
    electromagnetic one is now the same outline **composed** from ISO item 8.8
    X8126's parts, so it anchors what the composition's body anchors -- one
    body, three marks, one set of nozzles -- and ``Separator._VARIANT_ANCHORS``
    renames them, which is exactly what the unit half of the same change
    already did for the two beside it.
    """
    from pandid.render.symbols import default_registry

    symbol = default_registry.get("separator", variant)
    anchors = {"electromagnetic": ("feed", "vapor", "liquid")}.get(
        variant, ("feed", "overflow", "underflow")
    )
    assert (symbol.width, symbol.height) == (80.0, 120.0)
    assert symbol.ports == dict(zip(anchors, [(0.0, 12.0), (80.0, 12.0), (40.0, 120.0)]))
    # The overflow is on the side wall level with the feed; the underflow is the
    # hopper apex, the lowest point the artwork has.
    high, low = anchors[1], anchors[2]
    assert symbol.ports[high][1] == symbol.ports["feed"][1]
    assert symbol.ports[low][1] == symbol.height


def test_a_separator_variant_nobody_declared_still_gets_the_flash_drums_nozzles():
    """The port table falls back rather than guessing, exactly as the
    exchanger's does. Whether the variant name is real at all is the symbol
    registry's question, asked at render."""
    assert _nozzles(U.Separator("V-9", variant="not_a_variant")) == _FLASH_DRUM_NOZZLES


#: The four casings that take a cake off a medium and have to get rid of it.
_CAKE_FILTERS = ["press", "belt", "rotary", "rotary_scraper"]

#: The five that do not. Solids stay in the medium and come out offline, so one
#: in and one out is the whole of the piping.
_CLARIFYING_FILTERS = ["default", "fixed_bed", "gas", "gas_fixed_bed", "gas_belt"]


@pytest.mark.parametrize("variant", _CAKE_FILTERS)
def test_a_filter_that_forms_a_cake_draws_the_cake_and_takes_a_wash(variant):
    """A press separates a slurry into **two products**, and the cake is the one
    it was bought for. With one outlet the sheet had to draw it as the filtrate,
    which is the drawing saying the solids leave in the liquid line.

    ``wash_in`` is the displacement wash that pushes mother liquor out of the
    cake before it is discharged -- standard on all four of these -- and it
    takes ``utility`` for the reason an ejector's motive steam does: a service
    fluid supplied to the machine. The cake takes ``process``, because the role
    vocabulary has no word for wet solids, on the same reasoning the mechanical
    separators' draws are named by.

    Written out rather than read off ``_VARIANT_PORTS``, so this is the released
    API and not a restatement of the table that builds it.
    """
    assert _nozzles(U.Filter("F-101", variant=variant)) == [
        ("inlet", "inlet", "process"),
        ("wash_in", "inlet", "utility"),
        ("outlet", "outlet", "process"),
        ("cake", "outlet", "process"),
    ]


@pytest.mark.parametrize("variant", _CLARIFYING_FILTERS)
def test_a_clarifying_filter_keeps_the_two_nozzles_it_always_had(variant):
    """The other half of the split, and the half that must not move.

    A bag filter, a sand bed and the three gas casings hold their solids in the
    medium; what comes off them comes off when the medium is changed, backwashed
    or blown down, which is not a line on the sheet. Giving these four nozzles
    would draw a cake connection nothing is ever piped to.
    """
    filt = U.Filter("F-101", variant=variant)
    assert _nozzles(filt) == [
        ("inlet", "inlet", "process"),
        ("outlet", "outlet", "process"),
    ]
    with pytest.raises(AttributeError, match="available ports"):
        filt.cake


def test_an_ion_exchanger_names_its_regenerant_rather_than_borrowing_a_wash():
    """The variant that is neither family, and the reason it is neither.

    What restores a resin bed is acid, caustic or brine, and what leaves is that
    reagent carrying the ions it has stripped. ``wash_in`` on that line would put
    water on the line list where the pipe has to be rubber-lined for 30% HCl, so
    the pair is named for what it really carries.
    """
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


def test_a_filter_variant_nobody_declared_still_gets_the_clarifying_pair():
    """The port table falls back rather than guessing, as the exchanger's and
    the separator's do. Whether the variant name is real at all is the symbol
    registry's question, asked at render."""
    assert _nozzles(U.Filter("F-9", variant="not_a_variant")) == [
        ("inlet", "inlet", "process"),
        ("outlet", "outlet", "process"),
    ]


@pytest.mark.parametrize("variant", _CAKE_FILTERS + ["ion_exchange"])
def test_every_new_filter_nozzle_lands_somewhere_the_artwork_anchors(variant):
    """A nozzle the drawing does not place falls back to the centre of the box,
    where every other unplaced one lands too, and two streams stack on one point
    without anything being raised.

    The positions are the equipment's own. The wash and the regenerant come down
    from above; the cake and the spent regenerant leave downward, one because
    solids fall and the other through the underdrain below the bed. So both are
    on the horizontal casing walls the family leaves free -- these symbols are
    all piped across, west to east.
    """
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
    # The one on top is at y = 0 and the one underneath at the floor, and both
    # are inboard of the wall the feed comes in at.
    assert symbol.ports[into][1] == 0.0
    assert symbol.ports[out][1] == symbol.height
    assert symbol.ports[into][0] > inlet_x
    assert symbol.ports[out][0] > inlet_x


#: Every registered Dryer variant, general included: the default port set
#: applies uniformly today (see units.Dryer's own docstring), so there is
#: no split the way the filter's cake/clarifying one is.
_DRYER_VARIANTS = ["default", "general", "belt", "fluidized_bed", "shelf", "spray", "turbo"]


@pytest.mark.parametrize("variant", _DRYER_VARIANTS)
def test_a_drier_takes_a_heating_medium_in_and_sends_moisture_out(variant):
    """#345: two nozzles where the plant has four. A gas-suspension calciner
    tees its combustion chamber's hot gas into the solids feed line, and lets
    dried solid and off-gas leave together on one nozzle, because ``feed``
    and ``product`` were the whole of it; ``heating_in``/``vent`` are the
    two the plant actually has.

    Written out rather than read off ``_VARIANT_PORTS``, so this is the
    released API and not a restatement of the table that builds it -- the
    same discipline :func:`test_a_filter_that_forms_a_cake_draws_the_cake_and_takes_a_wash`
    holds Filter to.
    """
    assert _nozzles(U.Dryer("DR-1", variant=variant)) == [
        ("feed", "inlet", "feed"),
        ("product", "outlet", "process"),
        ("heating_in", "inlet", "utility"),
        ("vent", "outlet", "vapor"),
    ]


@pytest.mark.parametrize("variant", _DRYER_VARIANTS)
def test_every_driers_gas_nozzles_land_somewhere_the_artwork_anchors(variant):
    """No fallback to the centre of the box, on any registered variant --
    the same invariant :func:`test_every_new_filter_nozzle_lands_somewhere_the_artwork_anchors`
    holds Filter to, since ``heating_in``/``vent`` are just as new here."""
    from pandid.portgeom import is_anchored

    dryer = U.Dryer("DR-1", variant=variant)
    for name in dryer.ports:
        assert is_anchored(dryer, name), f"dryer/{variant} does not anchor {name!r}"


def test_a_drier_variant_nobody_declared_still_gets_all_four_nozzles():
    """The port table falls back rather than guessing, as the exchanger's,
    the separator's and the filter's do."""
    assert _nozzles(U.Dryer("DR-9", variant="not_a_variant")) == [
        ("feed", "inlet", "feed"),
        ("product", "outlet", "process"),
        ("heating_in", "inlet", "utility"),
        ("vent", "outlet", "vapor"),
    ]


def test_the_two_rotary_drums_are_piped_alike():
    """One machine drawn with and without the knife that lifts its cake.

    ``vendor_symbols`` already pins the filtrate outlet to the casing wall on
    the scraper drawing rather than letting it drift onto the arm, so that a
    sheet swapping one for the other moves no run. The wash and the cake follow
    that: same names, same points, five units of bounding box apart.
    """
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
    """``Unit._series_members`` backs
    :func:`pandid.portgeom._series_point`, which every port on a wide
    family (a splitter's numbered outlets, a column's feed on every
    stage) asks to be placed. Rescanning ``self.ports`` for the answer
    on every one of those asks cost the square of the family's size on
    the one unit carrying it; caching it per series is the fix, and the
    cache is read here before and after the one thing that can change
    the answer -- another port joining the family -- to show the second
    read is not the first one's stale copy.
    """
    from pandid.render.symbols import PortSeries

    s = U.Splitter("S", n_outlets=2)
    series = PortSeries("out_", "E")  # the one Splitter's own symbol declares
    assert s._series_members(series) == {"out_1": 0, "out_2": 1}

    # The only place after __init__ that writes ``self.ports``.
    s._add_port("out_3", "outlet", "process")
    assert s._series_members(series) == {"out_1": 0, "out_2": 1, "out_3": 2}


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


def test_one_feed_is_the_one_tuple_holding_feed_1():
    """The sequence is the general form and reads a one-feed and a
    three-feed column the same way, neither having to know which it got.

    A one-feed tower's nozzle is really named ``feed_1``, and ``feeds`` is
    that nozzle in a tuple; ``feed`` is the bare alias for the same
    ``Port`` object, not a second member of the family.
    """
    for one in (U.Column("T-101"), U.Reactor("R-101")):
        assert [p.name for p in one.feeds] == ["feed_1"]
        assert one.feeds[0] is one.feed


@pytest.mark.parametrize(
    ("build", "families"),
    [
        (lambda: U.Mixer("M", n_inlets=5), ["inlets"]),
        (lambda: U.Splitter("S", n_outlets=5), ["outlets"]),
        (lambda: U.Column("T", n_feeds=5), ["feeds"]),
        # ``feed_1`` is a numbered nozzle even at the default ``n_feeds=1``
        # this leaves in place, so "feeds" has to be checked here too, or
        # a single-feed column's own family would look incomplete.
        (lambda: U.Column("T", n_draws=5), ["draws", "feeds"]),
        (lambda: U.Column("T", n_feeds=5, n_draws=5), ["feeds", "draws"]),
        (lambda: U.Reactor("R", n_feeds=5), ["feeds"]),
        (lambda: U.Block("B", inputs=5, outputs=4), ["inlets", "outlets"]),
    ],
)
def test_a_family_is_every_numbered_nozzle_at_a_count_nothing_defaults_to(build, families):
    """Completeness, at an arity no default construction reaches.

    ``tests/test_port_annotations.py`` is what holds a family to the ports the
    class builds, and it builds one unit of each class with no arguments -- so a
    family that fell behind only at ``n_inlets=5`` would pass it untouched.
    This is the check that closes that: at five, every numbered nozzle in
    ``ports`` is in a family and every family member is a numbered nozzle, so a
    port added to the constructor without being added to the tuple has nowhere
    left to hide.
    """
    unit = build()
    numbered = {name for name in unit.ports if re.search(r"_\d+$", name)}
    in_families = {port.name for family in families for port in getattr(unit, family)}
    assert in_families == numbered
    assert sum(len(getattr(unit, family)) for family in families) == len(numbered)


def test_a_multi_feed_towers_family_is_its_numbered_nozzles_top_to_bottom():
    col = U.DistillationColumn("T-302", n_feeds=3)
    assert [p.name for p in col.feeds] == ["feed_1", "feed_2", "feed_3"]
    assert col.feeds[0] is col.feed_1
    # The other inlets are not charge nozzles, whatever their direction says.
    assert col.reflux_in not in col.feeds
    assert col.boilup_in not in col.feeds
    assert [p.name for p in U.Reactor("R-201", n_feeds=2).feeds] == ["feed_1", "feed_2"]


def test_a_multi_draw_towers_family_is_its_numbered_nozzles_top_to_bottom():
    # DistillationColumn, not Column: n_draws=3 with the reflux/boilup
    # nozzles for real, without the deprecated-nozzle path a plain Column
    # would take below. DistillationColumn gets no typed n_draws overload
    # family of its own (see Absorber/Stripper's own note on the same
    # trade), so draw_1 is read through port(), the untyped route.
    col = U.DistillationColumn("T-302", n_draws=3)
    assert [p.name for p in col.draws] == ["draw_1", "draw_2", "draw_3"]
    assert col.draws[0] is col.port("draw_1")
    # The draws are outlets on the east wall, not the returns beside them.
    assert col.reflux_in not in col.draws
    assert col.boilup_in not in col.draws
    assert col.feed not in col.draws


def test_one_draw_is_the_one_tuple_holding_the_singular_nozzle():
    col = U.Column("T-101", n_draws=1)
    assert [p.name for p in col.draws] == ["draw"]
    assert col.draws[0] is col.draw


def test_tank_is_its_own_kind():
    # Tank draws its own storage-tank symbol; it is not a Vessel alias.
    assert U.Tank is not U.Vessel
    assert U.Tank("T-1").kind == "tank"
    assert U.Vessel("V-1").kind == "vessel"


# ---------------------------------------------------------------------------
# A vessel's and a tank's five nozzles (#222)
# ---------------------------------------------------------------------------

#: What both classes offer, by name -- the spelling an author writes and
#: ``.port()`` resolves, ``inlet``/``outlet`` included even though #342 made
#: them live aliases for ``in_1``/``out_1`` rather than a second entry in
#: ``ports``. Written out rather than derived from ``PORTS``, which is the
#: thing under test: a list compared against itself would pass whatever it
#: said.
_HOLDUP_PORTS = ["inlet", "outlet", "vent", "relief", "drain"]


@pytest.mark.parametrize("cls", [U.Vessel, U.Tank], ids=["Vessel", "Tank"])
def test_a_vessel_and_a_tank_carry_the_same_five_nozzles(cls):
    """One shell at two design pressures, so one set of connections.

    0.1.1 gave a vessel a ``vent`` and a tank nothing, which said a tank does
    not breathe -- and left ``examples/14``'s fixed-roof ethanol tank unable to
    carry the conservation vent and its flame arrestor, which is issue #222.

    ``.ports`` itself now reads ``vent, relief, drain, in_1, out_1``, not the
    five names above: #342 gave ``inlet``/``outlet`` :class:`~pandid.units.
    Block`'s family mechanism, and ``vent``/``relief``/``drain`` are still
    ``PORTS``, which ``Unit.__init__`` lays down before a subclass's own
    ``__init__`` body adds anything else -- the fixed nozzles first and the
    family after, exactly the order :class:`~pandid.units.Column` already
    builds ``overhead``/``bottoms`` and then ``feeds``/``draws`` in.
    """
    assert list(cls("X-1").ports) == ["vent", "relief", "drain", "in_1", "out_1"]
    # And still every one of the five, under the name an author writes.
    assert all(name in _HOLDUP_PORTS or cls("X-1").port(name) for name in _HOLDUP_PORTS)


@pytest.mark.parametrize("cls", [U.Vessel, U.Tank], ids=["Vessel", "Tank"])
def test_the_three_fixed_nozzles_come_first(cls):
    """The family is appended, and that is what makes it additive.

    ``ports`` is insertion-ordered and observable -- a port family placed by a
    ``PortSeries`` is spread in the unit's own port order -- so weaving a new
    nozzle in among the old ones could move ink on a sheet that never asks for
    it. ``vent``, ``relief`` and ``drain`` are ``PORTS`` and so come first;
    ``in_1``/``out_1`` are ``_init_connections``'s and come after.
    """
    assert list(cls("X-1").ports)[:3] == ["vent", "relief", "drain"]


@pytest.mark.parametrize("cls", [U.Vessel, U.Tank], ids=["Vessel", "Tank"])
def test_each_added_nozzle_leaves_the_vessel_and_says_what_it_carries(cls):
    """Directions and roles, which is the half a name does not carry.

    ``relief`` is ``process`` and not ``vapor`` deliberately: what a relief
    passes is whatever the vessel is full of when it lifts, which on a fire case
    is liquid. ``drain`` is ``liquid`` because a low-point draw is not.
    """
    u = cls("X-1")
    assert [u.port(n).direction for n in _HOLDUP_PORTS] == ["inlet"] + ["outlet"] * 4
    assert u.vent.role == "vapor"
    assert u.relief.role == "process"
    assert u.drain.role == "liquid"


@pytest.mark.parametrize("cls", [U.Vessel, U.Tank], ids=["Vessel", "Tank"])
def test_the_three_fixed_nozzles_are_never_numbered(cls):
    """So ``nozzle-unconnected`` does not report a tank nobody drained.

    That finding reads a *count the author wrote down and did not meet*, which
    it recognises by the ``stem_N`` spelling. A named role is not a count: a
    vessel is offered a relief connection the way it has always been offered a
    vent, and leaving one open is a drawing decision. The rule is
    ``validate._family_stem``'s, and it is *asked* here rather than restated --
    a second copy of the naming rule is a second thing to keep in step.
    ``tests/test_validate.py`` holds the finding itself.

    ``in_1``/``out_1`` are the other two of the five and are genuinely
    numbered since #342: a plain, un-nozzled ``Tank("X-1")`` still draws no
    finding for them either, but for the *other* reason ``_family_stem``'s
    caller gives -- a live alias for a family's sole member, exactly as
    ``Reactor.feed`` is for ``feed_1`` -- and that reason is
    ``tests/test_validate.py``'s to hold, not this one's.
    """
    from pandid.validate import _family_stem

    assert [
        n
        for n in cls("X-1").ports
        if _family_stem(n) is not None and not n.startswith(("in_", "out_"))
    ] == []


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


def test_a_cooling_tower_names_its_two_sides_and_taps_its_basin():
    # The nozzles are named for the side of the equipment, as an exchanger's
    # are: which of the two is the hot one is the operating case. The other two
    # are what makes it a tower rather than an exchanger -- it evaporates part
    # of its own inventory, so something replaces it and something bleeds off
    # what is left behind.
    ct = U.CoolingTower("CT-101")
    assert list(ct.ports) == ["water_in", "water_out", "air_in", "air_out", "makeup", "blowdown"]
    assert ct.water_in.direction == "inlet"
    assert ct.water_out.direction == "outlet"
    assert ct.makeup.role == "utility"
    assert ct.blowdown.role == "liquid"


def test_both_cooling_tower_drafts_are_piped_alike():
    # Where the fan sits changes the casing and nothing else, so a sheet can
    # swap one drawing for the other without moving a run.
    drafts = [
        U.CoolingTower("CT-1", variant=v) for v in ("default", "induced_draft", "forced_draft")
    ]
    assert {tuple(ct.ports) for ct in drafts} == {tuple(drafts[0].ports)}


def test_open_ends_have_a_single_port_each_way():
    assert set(U.Vent("V-1").ports) == {"inlet"}
    assert U.Vent("V-1").inlet.direction == "inlet"
    assert set(U.Funnel("FN-1").ports) == {"outlet"}
    assert U.Funnel("FN-1").outlet.direction == "outlet"
