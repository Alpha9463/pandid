"""Check the draft-tube baffle crystallizer."""

import pytest

from pandid import Crystallizer, Feed, Flowsheet, Product
from pandid.portgeom import port_faces
from pandid.render import symbols
from pandid.render.symbols import MIN_NOZZLE_PITCH, default_registry, overlay_boxes

#: The registered body, without its agitator.
BODY = default_registry.get("crystallizer")


def _parts(unit):
    """Return the parts the unit's drawing carries."""
    return default_registry.for_unit(unit).overlays


def test_each_nozzle_leaves_by_its_own_face():
    """Check that feed, vapour, overflow and product leave W, N, E and S."""
    unit = Crystallizer("CR-101")
    faces = {name: port_faces(unit, name)[0] for name in unit.ports}
    assert faces == {"feed": "W", "vapor": "N", "overflow": "E", "product": "S"}


def test_the_propeller_hangs_inside_the_draft_tube():
    """Check that the default agitator is a propeller held between the tube walls."""
    parts = _parts(Crystallizer("CR-101"))
    assert [(o.group, o.name) for o in parts] == [(28, "propeller")]
    ((left, top, right, bottom),) = overlay_boxes(BODY, parts)
    tube_left = (BODY.width - symbols._CRYST_TUBE_W) / 2
    tube_right = (BODY.width + symbols._CRYST_TUBE_W) / 2
    assert tube_left < left < right < tube_right
    assert (left + right) / 2 == pytest.approx(BODY.width / 2), "the shaft is off the tube's axis"
    assert top == 0.0, "the shaft does not reach the head"
    assert symbols._CRYST_TUBE_TOP < bottom <= symbols._CRYST_TUBE_BOT


def test_the_vapour_nozzle_is_clear_of_the_shaft():
    """Check that the vapour line cannot be read as the agitator shaft."""
    vapor_x, vapor_y = BODY.ports["vapor"]
    assert abs(vapor_x - BODY.width / 2) >= MIN_NOZZLE_PITCH
    assert 0.0 < vapor_y < symbols._CRYST_HEAD, "the nozzle is not on the head"


def test_the_agitator_is_a_choice_fixed_at_construction():
    """Check that ``agitator=`` takes a group-28 name or ``None``, and nothing else."""
    assert _parts(Crystallizer("CR-101", agitator=None)) == ()
    turbine = Crystallizer("CR-102", agitator="turbine")
    assert [(o.group, o.name) for o in _parts(turbine)] == [(28, "turbine")]
    with pytest.raises(ValueError, match="agitator"):
        Crystallizer("CR-103", agitator="paddle wheel")
    with pytest.raises(AttributeError):
        turbine.agitator = "anchor"


def test_a_crystallizer_draws_on_a_sheet_and_is_scheduled():
    """Check a crystallizer piped on all four nozzles renders clean and is listed."""
    fs = Flowsheet("Crystallization")
    feed = fs.add(Feed("Feed Liquor"))
    cr = fs.add(Crystallizer("CR-101", description="Sulphate Crystallizer"))
    vapour = fs.add(Product("Vapour to Condenser"))
    fines = fs.add(Product("Fines to Dissolver"))
    slurry = fs.add(Product("Slurry to Centrifuge"))
    fs.connect(feed.outlet, cr.feed)
    fs.connect(cr.vapor, vapour.inlet)
    fs.connect(cr.overflow, fines.inlet)
    fs.connect(cr.product, slurry.inlet)

    svg = fs.to_svg()
    assert 'id="sym_crystallizer_' in svg
    assert [i for i in fs.validate() if i.severity == "error"] == []
    assert [row["tag"] for row in fs.equipment_list()] == ["CR-101"]
