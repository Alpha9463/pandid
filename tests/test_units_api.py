"""Ergonomics + spec fidelity of the units public surface."""

import inspect

import pytest

from pandid import units as U


def test_product_port_has_product_role():
    # Product's inlet has role "product", not the generic "process".
    assert U.Product("P1").inlet.role == "product"


def test_signal_terminals_carry_the_signal_role():
    """The role is what tells `connect()` a valve stem and an instrument's
    connections take a signal rather than fluid."""
    assert U.Valve("FV-101").actuator.role == "signal"
    inst = U.Instrument("FT", 101)
    assert [p.role for p in (inst.pv, inst.sig_in, inst.sig_out)] == ["signal"] * 3
    # ...and the process nozzles on the same valve are untouched.
    assert {U.Valve("FV-101").inlet.role, U.Valve("FV-101").outlet.role} == {"process"}


def test_unknown_port_attribute_gives_helpful_error():
    rx = U.Reactor("R1")
    with pytest.raises(AttributeError) as excinfo:
        _ = rx.effluent  # wrong name; the real port is "outlet"
    msg = str(excinfo.value)
    assert "effluent" in msg  # names what you asked for
    assert "outlet" in msg  # lists the ports that DO exist


def test_boundary_flags_take_an_off_page_reference():
    assert U.Feed("Raw Feed", reference="PFD-100").reference == "PFD-100"
    assert U.Product("To Flare", reference="PFD-900").reference == "PFD-900"


@pytest.mark.parametrize(
    "unit",
    [
        lambda: U.Pump("P-101", reference="PFD-100"),
        lambda: U.Column("T-101", reference="PFD-100"),
        lambda: U.Instrument("FT", 101, reference="PFD-100"),
    ],
)
def test_an_off_page_reference_on_equipment_is_refused(unit):
    # Only a boundary flag has a second line to draw it on, so anywhere else the
    # field would be stored and never seen.
    with pytest.raises(ValueError) as excinfo:
        unit()
    assert "Feed or Product" in str(excinfo.value)


def test_units_namespace_hides_internal_helpers():
    assert "Reactor" in U.__all__
    assert "Placement" not in U.__all__
    assert "Port" not in U.__all__


# ---------------------------------------------------------------------------
# The layer as API
# ---------------------------------------------------------------------------


def test_units_all_lists_every_public_unit_class():
    """The list is written by hand, and this is what keeps it honest.

    ``devices.__all__`` is generated because that whole module is; ``units.py``
    is hand-written, and a computed ``__all__`` there would have to re-derive
    the rule it is enforcing -- "a Unit subclass declared in this module, not
    underscore-prefixed" -- inside the module, where a reader looking for the
    public surface would find a comprehension instead of the surface. So the
    list stays a list you can read, and the rule lives here, which is the only
    place a class added tomorrow and left out is a *failure* rather than a
    silently smaller API.

    ``_Boundary`` and ``_NormallyPositioned`` are the two the rule excludes.
    Neither is a piece of plant: the first is what Feed and Product share and
    the second what a valve and a damper share. A name nobody constructs is a
    name nobody should be offered.

    ``_CrushingMachine`` used to be a third, ISO 10628-2 group 11's two
    nozzles shared by a crusher and a mill. It is public now, as
    ``CrushingMachine``, and draws item 11.1 X8084 -- the general machine an
    early PFD reaches for before process design has picked a jaw over a cone
    -- so a name is now something a caller does construct.
    """
    declared = {
        name
        for name, value in vars(U).items()
        if inspect.isclass(value)
        and issubclass(value, U.Unit)
        and value.__module__ == "pandid.units"
    }
    public = {name for name in declared if not name.startswith("_")}

    assert public == set(U.__all__)
    assert declared - public == {"_Boundary", "_NormallyPositioned"}


def test_every_unit_class_is_on_the_package():
    """``pandid.Separator`` and ``pandid.units.Separator`` are one class.

    The other half of "one hierarchy, one spelling": ``pandid.Cyclone`` has
    been importable since the device layer landed, and its own base class was
    reachable only as ``units.Separator``. Both stars in ``pandid/__init__.py``
    take a list nobody keeps by hand, so a class added to either module arrives
    here.
    """
    import pandid

    for name in U.__all__:
        assert getattr(pandid, name) is getattr(U, name)
        assert name in pandid.__all__


def test_no_unit_class_shadows_the_package_s_own_names():
    """A star import that took one of these would take it silently.

    ``units`` and ``devices`` are in the list because the namespaces stay
    importable: a unit class called ``units`` would replace the module object
    the ``Kind(variant=...)`` escape hatch is reached through, and the failure
    would surface as an ``AttributeError`` in someone else's sheet.
    """
    import pandid

    assert set(U.__all__).isdisjoint(
        {"Flowsheet", "Component", "SpecError", "units", "devices", "__version__"}
    )
    assert set(U.__all__).isdisjoint(pandid.devices.__all__)


def test_the_base_class_is_exported_for_the_custom_units_that_subclass_it():
    """Pinned, because it is the one name in the list you never instantiate.

    ``docs/api.md`` tells a custom unit to subclass ``Unit``; leaving it off
    would make the package's rule "every public name in units and devices,
    except the one the docs tell you to type" -- and the exception is the whole
    argument for stating a rule rather than keeping a list.
    """
    import pandid

    assert pandid.Unit is U.Unit
