# tests/test_serialize.py
from pfd import Flowsheet, Component, units as U


def test_to_dict_captures_topology():
    fs = Flowsheet("Demo", direction="LR")
    fs.add_component(Component("Water", "H2O"))
    feed = fs.add(U.Feed("Feed"))
    pump = fs.add(U.Pump("K-101"))
    fs.connect(feed.outlet, pump.suction, name="s-feed")

    d = fs.to_dict()
    assert d["name"] == "Demo"
    assert d["direction"] == "LR"
    assert d["components"] == ["Water"]

    unit_names = [u["name"] for u in d["units"]]
    assert unit_names == ["Feed", "K-101"]
    pump_entry = next(u for u in d["units"] if u["name"] == "K-101")
    assert {p["name"] for p in pump_entry["ports"]} == {"suction", "discharge"}

    assert d["streams"] == [
        {
            "name": "s-feed",
            "source": ["Feed", "outlet"],
            "dest": ["K-101", "suction"],
            "kind": "material",
            "is_recycle": False,
        }
    ]


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
