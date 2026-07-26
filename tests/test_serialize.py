# tests/test_serialize.py
from pfd import Component, Flowsheet, units as U


def test_to_dict_captures_topology():
    fs = Flowsheet("Demo")
    fs.add_component(Component("Water", "H2O"))
    feed = fs.add(U.Feed("Feed"))
    pump = fs.add(U.Pump("K-101"))
    fs.connect(feed.outlet, pump.suction, name="s-feed")

    d = fs.to_dict()
    assert d["name"] == "Demo"
    assert d["components"] == [{"name": "Water", "formula": "H2O"}]

    assert d["units"] == [
        {"kind": "Feed", "name": "Feed"},
        {"kind": "Pump", "name": "K-101"},
    ]
    assert d["streams"] == [
        {"from": ["Feed", "outlet"], "to": ["K-101", "suction"], "name": "s-feed"}
    ]


def test_to_dict_omits_defaults():
    """The spec is meant to be read and edited, so it carries intent only."""
    fs = Flowsheet("Plain")
    feed = fs.add(U.Feed("F"))
    prod = fs.add(U.Product("P"))
    fs.connect(feed.outlet, prod.inlet)

    d = fs.to_dict()
    assert "stream_naming_scheme" not in d
    assert "variant" not in d["units"][0]  # "default"
    assert "kind" not in d["streams"][0]  # "material"
    assert "name" not in d["streams"][0]  # auto-numbered, not the author's


def test_to_dict_is_json_serializable():
    """Adversarial check: ensure no hidden non-serializable types leak."""
    import json

    fs = Flowsheet("JSON-safe")
    feed = fs.add(U.Feed("F"))
    prod = fs.add(U.Product("P"))
    fs.connect(feed.outlet, prod.inlet)
    # This will raise TypeError if any value is not JSON-safe
    roundtrip = json.loads(json.dumps(fs.to_dict()))
    assert roundtrip["name"] == "JSON-safe"
    assert len(roundtrip["streams"]) == 1
