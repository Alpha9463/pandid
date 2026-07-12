"""State object (future M&E balance seam) — §4/§12 of the design spec.

The topology objects must carry a `state` slot now so a balance engine can
attach later without a rewrite.
"""

from pfd import Flowsheet, units as U
from pfd.state import State


def test_state_holds_composition_and_conditions():
    s = State(components={"NH3": 1.0}, molar_flow=10.0, T=300.0, P=101325.0)
    assert s.components["NH3"] == 1.0
    assert s.molar_flow == 10.0
    assert s.T == 300.0
    assert s.P == 101325.0


def test_state_defaults_are_empty():
    s = State()
    assert s.components == {}
    assert s.molar_flow is None


def test_port_and_stream_carry_state_defaulting_none():
    fs = Flowsheet("x")
    feed = fs.add(U.Feed("F"))
    prod = fs.add(U.Product("P"))
    stream = fs.connect(feed.outlet, prod.inlet)

    assert feed.outlet.state is None
    assert stream.state is None

    # The balance engine writes here later; the slot must accept a State.
    stream.state = State(molar_flow=5.0)
    feed.outlet.state = State(T=298.15)
    assert stream.state.molar_flow == 5.0
    assert feed.outlet.state.T == 298.15
