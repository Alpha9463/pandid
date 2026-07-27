from pandid.components import Component
from pandid.ports import Port


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


def test_stream_defaults():
    from pandid.streams import Stream

    src = Port(name="outlet", owner=None, direction="outlet", role="feed")
    dst = Port(name="inlet", owner=None, direction="inlet", role="feed")
    s = Stream(name="S1", source=src, dest=dst)
    assert s.name == "S1"
    assert s.source is src
    assert s.dest is dst
    assert s.kind == "material"
    assert s.is_recycle is False
    assert s.tear_hint is False
