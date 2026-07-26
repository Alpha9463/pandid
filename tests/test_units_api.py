"""Ergonomics + spec fidelity of the units public surface."""

import pytest

from pfd import units as U


def test_product_port_has_product_role():
    # Product's inlet has role "product", not the generic "process".
    assert U.Product("P1").inlet.role == "product"


def test_signal_terminals_carry_the_signal_role():
    """The role is what tells `connect()` a valve stem and an instrument's
    connections take a signal rather than fluid."""
    assert U.Valve("FV-101").actuator.role == "signal"
    inst = U.Instrument("FT", 101)
    assert [p.role for p in (inst.pv, inst.sig_in, inst.sig_out)] == ["signal"] * 3
    # ...and the process nozzles on the same valve are untouched.
    assert {U.Valve("FV-101").inlet.role, U.Valve("FV-101").outlet.role} == {"process"}


def test_unknown_port_attribute_gives_helpful_error():
    rx = U.Reactor("R1")
    with pytest.raises(AttributeError) as excinfo:
        _ = rx.effluent  # wrong name; the real port is "outlet"
    msg = str(excinfo.value)
    assert "effluent" in msg  # names what you asked for
    assert "outlet" in msg  # lists the ports that DO exist


def test_boundary_flags_take_an_off_page_reference():
    assert U.Feed("Raw Feed", reference="PFD-100").reference == "PFD-100"
    assert U.Product("To Flare", reference="PFD-900").reference == "PFD-900"


@pytest.mark.parametrize(
    "unit",
    [
        lambda: U.Pump("P-101", reference="PFD-100"),
        lambda: U.Column("T-101", reference="PFD-100"),
        lambda: U.Instrument("FT", 101, reference="PFD-100"),
    ],
)
def test_an_off_page_reference_on_equipment_is_refused(unit):
    # Only a boundary flag has a second line to draw it on, so anywhere else the
    # field would be stored and never seen.
    with pytest.raises(ValueError) as excinfo:
        unit()
    assert "Feed or Product" in str(excinfo.value)


def test_units_namespace_hides_internal_helpers():
    assert "Reactor" in U.__all__
    assert "Placement" not in U.__all__
    assert "Port" not in U.__all__
