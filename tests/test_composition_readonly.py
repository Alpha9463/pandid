"""Check that a composition keyword is fixed once the unit is built."""

import pytest

from pandid import Flowsheet
from pandid import units as U
from pandid.render.symbols import Overlay, default_registry


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


@pytest.mark.parametrize(
    ("build", "variant", "built"),
    [
        (
            lambda: U.Vessel("D-2", supports="ring"),
            "horizontal",
            lambda: U.Vessel("D-2", variant="horizontal", supports="ring"),
        ),
        (
            lambda: U.Reactor("R-1", agitator="propeller"),
            "tubular",
            lambda: U.Reactor("R-1", variant="tubular", agitator="propeller"),
        ),
        (
            lambda: U.Vessel("D-3", manholes=[("E", 0.5)]),
            "horizontal",
            lambda: U.Vessel("D-3", variant="horizontal", manholes=[("E", 0.5)]),
        ),
    ],
)
def test_a_variant_the_parts_cannot_go_on_is_refused_as_the_constructor_refuses_it(
    build, variant, built
):
    """Check that the refusal is the constructor's and leaves the unit as built."""
    unit = build()
    before = (unit.variant, unit.__dict__.get("overlays"))
    with pytest.raises(ValueError) as built_error:
        built()
    with pytest.raises(ValueError) as error:
        unit.variant = variant
    assert str(error.value) == str(built_error.value)
    assert (unit.variant, unit.__dict__.get("overlays")) == before
    sheet = Flowsheet("x")
    sheet.add(unit)
    sheet.to_svg()


def test_a_variant_the_parts_can_go_on_draws_them_as_the_constructor_would():
    """Check that a carried variant places the parts on the new body."""
    reactor = U.Reactor("R-1", agitator="propeller")
    reactor.variant = "jacketed"
    built = U.Reactor("R-1", variant="jacketed", agitator="propeller")
    assert reactor.__dict__["overlays"] == built.__dict__["overlays"]


@pytest.mark.parametrize("variant", ["default", "jacketed"], ids=["unchanged", "changed"])
def test_a_reassigned_variant_keeps_the_overlays_the_author_added(variant):
    """Check that only the composed parts are redrawn on the new body."""
    added = Overlay(27, "packing", 0, 0.3, 1, 0.3)
    reactor = U.Reactor("R-1", agitator="propeller")
    reactor.overlays = (*reactor.__dict__["overlays"], added)
    reactor.variant = variant
    built = U.Reactor("R-1", variant=variant, agitator="propeller")
    assert reactor.__dict__["overlays"] == (*built.__dict__["overlays"], added)
    assert added in default_registry.for_unit(reactor).overlays


def test_a_variant_is_refused_once_the_built_parts_are_edited():
    """Check that edited composed parts refuse a new body and stay as the author left them."""
    reactor = U.Reactor("R-1", agitator="propeller")
    edited = reactor.__dict__["overlays"][:1]
    reactor.overlays = edited
    with pytest.raises(ValueError, match=r"Reactor\('R-1', \.\.\., variant='jacketed'\)"):
        reactor.variant = "jacketed"
    assert (reactor.variant, reactor.__dict__["overlays"]) == ("default", edited)
