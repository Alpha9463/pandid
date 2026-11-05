"""Run the custom unit workflow documented in ``docs/api.md`` end to end."""

import pytest

from pandid import Flowsheet, units
from pandid.document import equipment_table
from pandid.portgeom import port_point
from pandid.render.symbols import Symbol, default_registry
from pandid.spec import SpecError

# Straight sides on a cone: feed and mother liquor at the walls, crystals out the bottom.
CRYSTALLISER_SVG = (
    '<g id="sym_crystalliser">'
    '<path d="M 5 5 L 5 45 L 35 65 L 45 65 L 75 45 L 75 5 Z" '
    'fill="none" stroke="black" stroke-width="2"/>'
    "</g>"
)

FORCED_CIRCULATION_SVG = (
    '<g id="sym_crystalliser_fc">'
    '<path d="M 5 5 L 5 45 L 35 65 L 45 65 L 75 45 L 75 5 Z" '
    'fill="none" stroke="black" stroke-width="2"/>'
    '<circle cx="40" cy="25" r="12" fill="none" stroke="black" stroke-width="2"/>'
    "</g>"
)


class Crystalliser(units.Unit):
    kind = "crystalliser"
    PORTS = [
        ("feed", "inlet", "process"),
        ("mother_liquor", "outlet", "process"),
        ("crystals", "outlet", "process"),
    ]


class Neutraliser(units.Unit):
    """A custom unit nobody drew a symbol for: it gets the generic box."""

    kind = "neutraliser_test_unit"
    PORTS = [("inlet", "inlet", "process"), ("outlet", "outlet", "process")]


def _crystalliser_symbol(svg=CRYSTALLISER_SVG):
    return Symbol(
        svg=svg,
        width=80.0,
        height=70.0,
        ports={
            "feed": (5.0, 15.0),
            "mother_liquor": (75.0, 15.0),
            "crystals": (40.0, 65.0),
        },
    )


@pytest.fixture
def crystalliser():
    """Register the documented symbol, and take it back out afterwards."""
    default_registry.register("crystalliser", _crystalliser_symbol())
    yield
    for variant in ("default", "forced_circulation"):
        default_registry._symbols.pop(("crystalliser", variant), None)


def _plant(unit):
    """Return a sheet with a feed, the unit and a product on each outlet, every line tabulated."""
    fs = Flowsheet("Salt Plant")
    brine = fs.add(units.Feed("Brine"))
    fs.add(unit)
    fs.connect(brine.outlet, unit.ports["feed" if "feed" in unit.ports else "inlet"]).properties = {
        "Flow (kg/h)": "4200"
    }
    for name, port in unit.ports.items():
        if port.direction == "outlet":
            product = fs.add(units.Product(f"P-{name}"))
            fs.connect(port, product.inlet).properties = {"Flow (kg/h)": "4200"}
    return fs


def test_a_custom_unit_declares_its_ports_like_a_shipped_one():
    cr = Crystalliser("CR-101", description="Salt Crystalliser")
    assert cr.kind == "crystalliser"
    assert set(cr.ports) == {"feed", "mother_liquor", "crystals"}
    assert cr.feed is cr.ports["feed"]
    assert cr.feed.direction == "inlet"
    assert cr.crystals.direction == "outlet"
    assert cr.crystals.role == "process"
    assert cr.feed.owner is cr


def test_an_invalid_role_is_refused_when_the_unit_is_built():
    class _Bad(units.Unit):
        kind = "bad_test_unit"
        PORTS = [("feed", "inlet", "slurry")]

    with pytest.raises(ValueError, match="Invalid role 'slurry'"):
        _Bad("X-1")


def test_the_documented_example_draws_the_custom_symbol(crystalliser):
    """The whole workflow: subclass, register, build, validate, lay out, draw."""
    cr = Crystalliser("CR-101", description="Salt Crystalliser")
    fs = _plant(cr)

    assert fs.validate() == []
    fs.layout()
    fs.route()
    svg = fs.to_svg()

    # The artwork is defined once, under an id made from the kind, and placed by reference.
    assert '<symbol id="sym_crystalliser"' in svg
    assert "M 5 5 L 5 45 L 35 65" in svg
    assert 'href="#sym_crystalliser"' in svg
    assert [i for i in fs.warnings if i.code == "coincident-ports"] == []

    frame = cr.frame
    assert (frame.w, frame.h) == (80.0, 70.0)
    assert port_point(cr, frame, "feed") == (frame.x + 5.0, frame.y + 15.0)
    assert port_point(cr, frame, "mother_liquor") == (frame.x + 75.0, frame.y + 15.0)
    assert port_point(cr, frame, "crystals") == (frame.x + 40.0, frame.y + 65.0)


def test_a_variant_is_a_second_style_of_the_same_kind(crystalliser):
    default_registry.register(
        "crystalliser", _crystalliser_symbol(FORCED_CIRCULATION_SVG), variant="forced_circulation"
    )
    assert default_registry.variants("crystalliser") == ["default", "forced_circulation"]

    fs = _plant(Crystalliser("CR-102", variant="forced_circulation"))
    svg = fs.to_svg()
    assert 'href="#sym_crystalliser_forced_circulation"' in svg
    assert '<circle cx="40" cy="25" r="12"' in svg

    with pytest.raises(ValueError, match="crystalliser has no variant 'draft_tube'"):
        _plant(Crystalliser("CR-103", variant="draft_tube")).to_svg()


def test_a_kind_with_no_symbol_draws_a_generic_box():
    """The cheap path: no artwork registered at all still gives a drawing."""
    unit = Neutraliser("N-101")
    fs = _plant(unit)
    svg = fs.to_svg()
    assert 'href="#sym_neutraliser_test_unit"' in svg
    assert '<rect x="0" y="0" width="60" height="60"' in svg
    assert (unit.frame.w, unit.frame.h) == (60.0, 60.0)
    # Every port fell back to the box centre, which warns and still draws.
    assert [i.severity for i in fs.warnings if i.code == "coincident-ports"] == ["warning"]


def test_a_port_the_symbol_never_anchored_warns_rather_than_raising():
    """Check that a nozzle the symbol does not anchor warns and still draws."""
    half_drawn = Symbol(
        svg=CRYSTALLISER_SVG.replace("sym_crystalliser", "sym_crystalliser_partial"),
        width=80.0,
        height=70.0,
        ports={"feed": (5.0, 15.0)},
    )
    default_registry.register("crystalliser", half_drawn)
    try:
        fs = _plant(Crystalliser("CR-104"))
        fs.layout()
        issues = [i for i in fs.validate() if i.code == "coincident-ports"]
        assert [i.severity for i in issues] == ["warning"]
        assert "anchors no nozzle" in issues[0].message
        fs.to_svg()  # must not raise
    finally:
        default_registry._symbols.pop(("crystalliser", "default"), None)


def test_a_subclass_declaration_replaces_the_one_above_it():
    """Check that a subclass's ``PORTS`` replaces the inherited list."""

    class _Base(units.Unit):
        kind = "override_base_test_unit"
        PORTS = [("inlet", "inlet", "process"), ("outlet", "outlet", "process")]

    class _Narrow(_Base):
        kind = "override_narrow_test_unit"
        PORTS = [("inlet", "inlet", "process")]

    assert set(_Narrow("B-1").ports) == {"inlet"}


def test_a_custom_unit_cannot_be_written_to_a_spec(crystalliser):
    """Check that writing a custom unit to a spec is refused."""
    fs = _plant(Crystalliser("CR-105"))
    with pytest.raises(SpecError, match="not one of the built-in equipment classes"):
        fs.to_dict()


def test_a_custom_unit_is_scheduled_only_when_it_is_named(crystalliser):
    """Check that a custom unit is on the equipment list only when named."""
    cr = Crystalliser("CR-106", description="Salt Crystalliser")
    fs = _plant(cr)
    assert [row for row in equipment_table(fs).rows if row[0] == "CR-106"] == []
    assert equipment_table(fs, include=["CR-106"]).rows == [("CR-106", "Salt Crystalliser")]
    assert equipment_table(_plant(Crystalliser("CR-107")), include=["CR-107"]).rows == [
        ("CR-107", "Crystalliser")
    ]


def test_a_spec_cannot_name_a_custom_kind(crystalliser):
    with pytest.raises(SpecError, match="unknown equipment kind 'crystalliser'"):
        Flowsheet.from_dict(
            {"name": "Salt Plant", "units": [{"kind": "crystalliser", "name": "CR-101"}]}
        )
