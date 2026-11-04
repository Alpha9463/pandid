"""Check that a composition keyword is fixed once the unit is built."""

import pytest

from pandid import units as U


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
        (lambda: U.Absorber("X-1"), "internals", "baffle_tray"),
        (lambda: U.Stripper("X-1", internals="tray", trays=10), "internals", "baffle_tray"),
        (
            lambda: U.DistillationColumn("X-1", internals="tray", trays=10),
            "internals",
            "baffle_tray",
        ),
    ],
)
def test_a_composition_keyword_refuses_reassignment_naming_the_kwarg(build, attr, new_value):
    unit = build()
    before = getattr(unit, attr)
    with pytest.raises(AttributeError, match=attr):
        setattr(unit, attr, new_value)
    assert getattr(unit, attr) == before


def test_width_and_height_are_unaffected_and_still_live():
    """Check that width, height and description can still be reassigned."""
    col = U.Column("T-1", width=50, height=200)
    col.width = 80
    assert col.width == 80
    col.description = "revised"
    assert col.description == "revised"
