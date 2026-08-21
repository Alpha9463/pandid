"""#415: a composition keyword is read once, in ``__init__``, to build
the nozzles and overlays that describe what a unit *is* -- and, unlike
``width``/``height``, was never read again. Reassigning one raised
nothing and changed nothing, silently leaving the object disagreeing
with the drawing already built from its first answer.

Fixed by refusing the reassignment outright (see
:attr:`pandid.units.Unit._FIXED_AT_CONSTRUCTION`), the same answer
:attr:`~pandid.units.Tee.branch_direction` already gives a caller who
tries to turn a takeoff into a return after the nozzle is built.
"""

import pytest

from pandid import Flowsheet, units as U


def test_reassigning_column_feed_stages_is_refused_not_silently_ignored():
    """The exact reproduction from #415."""
    fs = Flowsheet("repro")
    col = fs.add(U.Column("T-101", internals="tray", trays=30, n_feeds=1, feed_stages=[5]))
    new_stages: list[int | None] = [25]
    with pytest.raises(AttributeError, match="feed_stages"):
        col.feed_stages = new_stages
    # Refused, not silently accepted and then ignored: the value the
    # constructor was given is still the one on the object.
    assert col.feed_stages == [5]


@pytest.mark.parametrize(
    ("build", "attr", "new_value"),
    [
        (lambda: U.Column("T-1", internals="tray", trays=10), "internals", "packing"),
        (lambda: U.Column("T-1", internals="tray", trays=10), "trays", 20),
        (
            lambda: U.Column("T-1", internals="tray", trays=10, feed_stages=[3]),
            "feed_stages",
            [7],
        ),
        (
            lambda: U.Column("T-1", internals="tray", trays=10, n_draws=1, draw_stages=[3]),
            "draw_stages",
            [7],
        ),
        (lambda: U.Reactor("R-1", agitator="turbine"), "agitator", "propeller"),
        (lambda: U.Reactor("R-1", internals="packing"), "internals", "fluidised_bed"),
        (lambda: U.Vessel("V-1", supports="leg"), "supports", "skirt"),
    ],
)
def test_a_composition_keyword_refuses_reassignment_naming_the_kwarg(build, attr, new_value):
    unit = build()
    before = getattr(unit, attr)
    with pytest.raises(AttributeError, match=attr):
        setattr(unit, attr, new_value)
    # Nothing moved: the object still answers the way it was built.
    assert getattr(unit, attr) == before


@pytest.mark.parametrize("cls", [U.Absorber, U.Stripper, U.DistillationColumn])
def test_every_column_subclass_refuses_internals_reassignment_uniformly(cls):
    """#415 asked for one answer covering the whole family, not a
    plain ``Column`` refusing while a subclass quietly accepts."""
    kwargs = {"internals": "tray", "trays": 10} if cls is not U.Absorber else {}
    unit = cls("X-1", **kwargs)
    with pytest.raises(AttributeError, match="internals"):
        unit.internals = "baffle_tray"


def test_width_and_height_are_unaffected_and_still_live():
    """The fix narrows to the composition keywords; the geometry a
    unit is placed with was already live and stays that way."""
    col = U.Column("T-1", width=50, height=200)
    col.width = 80
    assert col.width == 80
    col.description = "revised"
    assert col.description == "revised"


def test_a_stale_feed_stage_can_no_longer_reach_route():
    """The stronger claim #415 made: since the reassignment itself is
    refused, a routed sheet can never disagree with the stage a feed
    was actually built on."""
    fs = Flowsheet("repro")
    col = fs.add(U.Column("T-101", internals="tray", trays=30, n_feeds=1, feed_stages=[5]))
    feed = fs.add(U.Feed("F"))
    fs.connect(feed.outlet, col.feed_1)
    prod1 = fs.add(U.Product("P1"))
    prod2 = fs.add(U.Product("P2"))
    fs.connect(col.overhead, prod1.inlet)
    fs.connect(col.bottoms, prod2.inlet)
    new_stages: list[int | None] = [25]
    with pytest.raises(AttributeError):
        col.feed_stages = new_stages
    fs.layout()
    fs.route()
    assert col.feed_stages == [5]  # what the drawing was actually built from
