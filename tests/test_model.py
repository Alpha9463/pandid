# tests/test_model.py
from pfd.components import Component
from pfd.ports import Port


def test_component_holds_name_and_formula():
    c = Component("Water", formula="H2O")
    assert c.name == "Water"
    assert c.formula == "H2O"


def test_component_formula_optional():
    assert Component("Nitrogen").formula is None


def test_port_fields_and_default_stream():
    p = Port(name="outlet", owner=None, direction="outlet", role="feed")
    assert p.name == "outlet"
    assert p.direction == "outlet"
    assert p.role == "feed"
    assert p.side is None
    assert p.stream is None
