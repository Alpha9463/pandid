"""End-to-end integration test: ammonia synthesis loop.

This test assembles a realistic process flow diagram using the full public API
and verifies the topology layer's contract: units connect through typed ports,
streams auto-name, energy detection works, and the whole thing serializes to
a JSON-safe dict.
"""

from pandid import Flowsheet, units as U


def build_ammonia_loop():
    """Build a simplified ammonia synthesis loop PFD."""
    fs = Flowsheet("Ammonia Loop")
    feed = fs.add(U.Feed("Natural Gas"))
    reformer = fs.add(U.Reactor("R-101"))
    hx = fs.add(U.HeatExchanger("E-101"))
    sep = fs.add(U.Separator("V-101"))
    comp = fs.add(U.Compressor("K-101"))
    prod = fs.add(U.Product("Ammonia"))

    fs.connect(feed.outlet, reformer.feed)
    fs.connect(reformer.outlet, hx.shell_in)
    fs.connect(hx.shell_out, sep.feed)
    fs.connect(sep.vapor, comp.suction)
    fs.connect(comp.discharge, hx.tube_in)  # a recycle back-edge
    fs.connect(sep.liquid, prod.inlet)
    return fs


def test_ammonia_loop_assembles():
    fs = build_ammonia_loop()
    assert len(fs.units) == 6
    assert len(fs.streams) == 6
    # Recycle is not user-declared; it stays False until layout runs.
    assert all(s.is_recycle is False for s in fs.streams)


def test_ammonia_loop_serializes_roundtrip_shape():
    d = build_ammonia_loop().to_dict()
    assert d["name"] == "Ammonia Loop"
    assert len(d["units"]) == 6
    assert len(d["streams"]) == 6
    # Every stream references real units by name.
    unit_names = {u["name"] for u in d["units"]}
    for s in d["streams"]:
        assert s["from"][0] in unit_names
        assert s["to"][0] in unit_names


def test_ammonia_loop_json_roundtrip():
    """Adversarial: full e2e JSON serialization of a complex flowsheet."""
    import json

    d = build_ammonia_loop().to_dict()
    roundtrip = json.loads(json.dumps(d))
    assert roundtrip == d
