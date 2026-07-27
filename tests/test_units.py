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
    assert set(U.HeatExchanger("E").ports) == {"hot_in", "hot_out", "cold_in", "cold_out"}
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


def test_only_the_kettle_carries_the_bottoms_draw():
    """A plate exchanger has no weir, so handing every hex the nozzle would give
    most of them one the symbol cannot place."""
    plate = U.HeatExchanger("E-1", variant="plate")
    assert "bottoms" not in plate.ports
    with pytest.raises(AttributeError, match="available ports"):
        plate.bottoms


def test_mixer_variable_inlets():
    m = U.Mixer("M", n_inlets=3)
    assert set(m.ports) == {"in_1", "in_2", "in_3", "outlet"}
    assert m.in_2.direction == "inlet"
    assert m.outlet.direction == "outlet"


def test_splitter_variable_outlets():
    s = U.Splitter("S", n_outlets=3)
    assert set(s.ports) == {"inlet", "out_1", "out_2", "out_3"}
    assert s.out_3.direction == "outlet"


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
