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
        _PORTS = [("x", "inlet", "a"), ("x", "outlet", "b")]

    with pytest.raises(ValueError, match="already has a port named 'x'"):
        _Bad("B-1")
