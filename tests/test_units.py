# tests/test_units.py
import pytest
from pfd.units import Unit
from pfd.ports import Port


class _Widget(Unit):
    kind = "widget"
    _PORTS = [("inlet", "inlet", "process"), ("outlet", "outlet", "process")]


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
        _PORTS = [("x", "inlet", "process"), ("x", "outlet", "process")]

    with pytest.raises(ValueError, match="already has a port named 'x'"):
        _Bad("B-1")


def test_invalid_port_role_raises():
    class _BadRole(Unit):
        kind = "badrole"
        _PORTS = [("in", "inlet", "magic")]

    with pytest.raises(ValueError, match="Invalid role 'magic'"):
        _BadRole("B-2")


# --- Task 5: Built-in unit types ---

from pfd import units as U  # noqa: E402


def test_fixed_port_units_have_expected_ports():
    assert set(U.Feed("F").ports) == {"outlet"}
    assert set(U.Product("P").ports) == {"inlet"}
    assert set(U.Pump("K").ports) == {"suction", "discharge"}
    assert set(U.HeatExchanger("E").ports) == {"hot_in", "hot_out", "cold_in", "cold_out"}
    assert set(U.Separator("V").ports) == {"feed", "vapor", "liquid"}
    assert set(U.Column("T").ports) == {
        "feed", "distillate", "bottoms", "reboiler_duty", "condenser_duty"
    }


def test_reactor_duty_is_energy_role():
    r = U.Reactor("R")
    assert r.duty.role == "energy"
    assert r.feed.direction == "inlet"
    assert r.outlet.direction == "outlet"


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
    # Tank is now a distinct storage-tank symbol, not a Vessel alias.
    assert U.Tank is not U.Vessel
    assert U.Tank("T-1").kind == "tank"
    assert U.Vessel("V-1").kind == "vessel"


def test_mixer_rejects_zero_inlets():
    with pytest.raises(ValueError, match="at least 1 inlet"):
        U.Mixer("M", n_inlets=0)


def test_splitter_rejects_zero_outlets():
    with pytest.raises(ValueError, match="at least 1 outlet"):
        U.Splitter("S", n_outlets=0)
