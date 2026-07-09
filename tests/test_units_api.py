"""Ergonomics + spec fidelity of the units public surface."""

import pytest

from pfd import units as U


def test_product_port_has_product_role():
    # Spec §4 table: Product's inlet has role "product", not the generic "process".
    assert U.Product("P1").inlet.role == "product"


def test_unknown_port_attribute_gives_helpful_error():
    rx = U.Reactor("R1")
    with pytest.raises(AttributeError) as excinfo:
        _ = rx.effluent  # wrong name; the real port is "outlet"
    msg = str(excinfo.value)
    assert "effluent" in msg          # names what you asked for
    assert "outlet" in msg            # lists the ports that DO exist


def test_units_namespace_hides_internal_helpers():
    assert "Reactor" in U.__all__
    assert "Placement" not in U.__all__
    assert "Port" not in U.__all__
