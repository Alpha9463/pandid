"""Persist stream-relative preferences on explicitly wired inline devices."""

from __future__ import annotations

import pytest

from pandid import Feed, Flowsheet, Product, Reducer, Valve
from pandid.layout.backbone import infer_backbone
from pandid.spec import SpecError
from pandid.state import State
from pandid.streams import Stream


def _wired_chain() -> tuple[Flowsheet, Stream, Valve, Reducer]:
    """Build a small run with an actuated valve and a reducer.

    Returns
    -------
    tuple[Flowsheet, Stream, Valve, Reducer]
        Sheet, inlet segment, valve, and reducer.
    """
    fs = Flowsheet("Inline intent")
    feed = fs.add(Feed("Feed"))
    valve = fs.add(Valve("CV-101", variant="control"))
    reducer = fs.add(Reducer("RD-101"))
    product = fs.add(Product("Product"))
    inlet = fs.connect(feed.outlet, valve.inlet, size=6, service="P")
    fs.connect(valve.outlet, reducer.inlet)
    fs.connect(reducer.outlet, product.inlet)
    controller = fs.add_instrument("FIC", 101, near=valve, at="N")
    fs.connect(controller.sig_out, valve.actuator, kind="electric")
    fs.add_instrument("FT", 101, sensing=inlet, at=0.3)
    return fs, inlet, valve, reducer


def test_inline_intent_round_trips_without_rewiring() -> None:
    """Retain physical references, line numbers, signals, and intent.

    Returns
    -------
    None
        The backbone and spec retain both run fractions.
    """
    fs, inlet, valve, reducer = _wired_chain()
    downstream = fs.streams[1]
    instrument = fs.units[-1]
    state = State(T=300)
    inlet.state = state
    before = [(s.name, s.sequence, s.source, s.dest) for s in fs.streams]
    before_svg = fs.to_svg()

    fs._set_inline_at(inlet, 0.25)
    fs._set_inline_at(downstream, 0.75)

    assert [(s.name, s.sequence, s.source, s.dest) for s in fs.streams] == before
    assert inlet.dest.owner is valve
    assert downstream.dest.owner is reducer
    assert instrument.host is inlet
    assert inlet.state is state
    assert valve.actuator.stream is fs.streams[-1]
    assert fs.to_svg() == before_svg
    assert infer_backbone(fs).runs[0].inline_at == (0.25, 0.75)
    written = fs.to_dict()
    assert [entry.get("inline_at") for entry in written["streams"]] == [0.25, 0.75, None, None]

    rebuilt = Flowsheet.from_dict(written)
    assert rebuilt.to_dict() == written
    assert rebuilt.units[-1].host is rebuilt.streams[0]
    assert rebuilt.streams[-1].dest.owner.name == "CV-101"
    assert infer_backbone(rebuilt).runs[0].inline_at == (0.25, 0.75)


@pytest.mark.parametrize("at", [0, 1, -0.1, 1.1, float("inf"), float("nan"), True, "0.5"])
def test_invalid_inline_fraction_leaves_sheet_unchanged(at: object) -> None:
    """Reject invalid fractions before storing any intent.

    Parameters
    ----------
    at : object
        Invalid candidate fraction.

    Returns
    -------
    None
        The sheet specification remains unchanged.
    """
    fs, inlet, _, _ = _wired_chain()
    before = fs.to_dict()
    with pytest.raises(ValueError, match="inline position"):
        fs._set_inline_at(inlet, at)  # type: ignore[arg-type]
    assert fs.to_dict() == before


def test_inline_intent_rejects_foreign_and_defers_to_exact_pins() -> None:
    """Require local segments and keep exact pins authoritative.

    Returns
    -------
    None
        A foreign segment is refused and an exact pin stays intact.
    """
    fs, inlet, valve, _ = _wired_chain()
    other, foreign, _, _ = _wired_chain()
    before = fs.to_dict()
    with pytest.raises(ValueError, match="another flowsheet"):
        fs._set_inline_at(foreign, 0.5)
    assert fs.to_dict() == before
    valve.pin(x=300)
    fs._set_inline_at(inlet, 0.5)
    assert valve.pin_ is not None and valve.pin_.x == 300
    assert valve in [fs.units[i] for i in infer_backbone(fs).nodes]
    assert Flowsheet.from_dict(fs.to_dict()).to_dict() == fs.to_dict()
    assert other.streams[0]._inline_at is None


def test_spec_rejects_inline_position_on_non_inline_segment() -> None:
    """Report the offending spec path for an invalid attachment.

    Returns
    -------
    None
        The error identifies the stream entry.
    """
    fs, _, _, _ = _wired_chain()
    data = fs.to_dict()
    data["streams"][2]["inline_at"] = 0.5
    with pytest.raises(SpecError, match=r"streams\[2\]\.inline_at"):
        Flowsheet.from_dict(data)
