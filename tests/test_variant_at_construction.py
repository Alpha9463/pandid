"""Check that reassigning a variant that builds the unit is deprecated."""

import warnings
from collections.abc import Callable

import pytest

from pandid import Flowsheet
from pandid import units as U

BUILT_FROM_VARIANT: list[tuple[Callable[[], U.Unit], str]] = [
    (lambda: U.Valve("V-1"), "three_way"),
    (lambda: U.Vessel("D-1"), "dished"),
    (lambda: U.Tank("T-1"), "conical"),
    (lambda: U.Filter("F-1"), "press"),
    (lambda: U.HeatExchanger("E-1"), "kettle"),
    (lambda: U.Reactor("R-1", agitator=None), "tubular"),
    (lambda: U.Separator("S-1"), "cyclone"),
]


@pytest.mark.parametrize(
    ("build", "variant"), BUILT_FROM_VARIANT, ids=[v for _, v in BUILT_FROM_VARIANT]
)
def test_reassigning_a_variant_the_ports_come_from_is_deprecated(build, variant):
    """Check the warning and the finding name the unit and the call to use instead."""
    unit = build()
    with pytest.warns(DeprecationWarning, match="use a new unit built with variant="):
        unit.variant = variant
    assert unit.variant == variant
    fs = Flowsheet("x")
    fs.add(unit)
    found = [issue for issue in fs.validate() if issue.code == "deprecated"]
    assert len(found) == 1
    assert found[0].message.startswith(f"{unit.name}: ")


@pytest.mark.parametrize(
    ("build", "variant"),
    [
        (lambda: U.Conveyor("CV-1", length=80), "screw"),
        (lambda: U.Pump("P-1"), "gear"),
        (lambda: U.Fitting("ST-1"), "strainer"),
    ],
    ids=["conveyor", "pump", "fitting"],
)
def test_reassigning_a_variant_the_ports_do_not_come_from_is_not(build, variant):
    """Check that a unit built the same way for every variant takes a new one quietly."""
    unit = build()
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        unit.variant = variant
    assert unit.variant == variant
