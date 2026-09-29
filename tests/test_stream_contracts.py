"""Verify public stream properties and serialized inline-placement rules."""

import pytest

from pandid import Feed, Flowsheet, Product, Valve
from pandid.spec import SpecError


def _inline_chain() -> Flowsheet:
    """Build a material chain containing one inline-capable valve.

    Returns
    -------
    pandid.Flowsheet
        Unpositioned feed, valve, and product connected in material order.
    """
    flowsheet = Flowsheet("Stream contracts")
    feed = flowsheet.add(Feed("Feed"))
    valve = flowsheet.add(Valve("HV-101"))
    product = flowsheet.add(Product("Product"))
    flowsheet.connect(feed.outlet, valve.inlet)
    flowsheet.connect(valve.outlet, product.inlet)
    return flowsheet


def test_is_recycle_is_read_only_until_layout_marks_a_stream() -> None:
    """Verify that callers cannot assign the layout-owned recycle flag.

    Returns
    -------
    None
        The stream retains its default non-recycle state.
    """
    stream = _inline_chain().streams[0]

    assert stream.is_recycle is False
    with pytest.raises(AttributeError):
        setattr(stream, "is_recycle", True)
    assert stream.is_recycle is False


def test_spec_rejects_an_inline_position_on_an_outgoing_segment() -> None:
    """Verify that a serialized inline position identifies its invalid stream.

    Returns
    -------
    None
        The reader reports the outgoing segment's ``inline_at`` field.
    """
    data = _inline_chain().to_dict()
    data["streams"][1]["inline_at"] = 0.5

    with pytest.raises(SpecError, match=r"streams\[1\]\.inline_at"):
        Flowsheet.from_dict(data)
