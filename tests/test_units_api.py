"""Ergonomics + spec fidelity of the units public surface."""

import inspect
from importlib import import_module

import pytest

from pandid import units as U


def test_product_port_has_product_role():
    assert U.Product("P1").inlet.role == "product"


def test_signal_terminals_carry_the_signal_role():
    """Check that valve actuators and instrument terminals have the signal role."""
    assert U.Valve("FV-101").actuator.role == "signal"
    inst = U.Instrument("FT", 101)
    assert [p.role for p in (inst.pv, inst.sig_in, inst.sig_out)] == ["signal"] * 3
    assert {U.Valve("FV-101").inlet.role, U.Valve("FV-101").outlet.role} == {"process"}


def test_boundary_flags_take_an_off_page_reference():
    assert U.Feed("Raw Feed", reference="PFD-100").reference == "PFD-100"
    assert U.Product("To Flare", reference="PFD-900").reference == "PFD-900"


@pytest.mark.parametrize("cls", [U.Mixer, U.Splitter])
def test_mixer_and_splitter_take_label_pos_like_every_other_tagged_unit(cls):
    """Check that a mixer and a splitter take ``label_pos=``."""
    unit = cls("X", label_pos="top")
    assert unit.label_pos == "top"


@pytest.mark.parametrize(
    "unit",
    [
        lambda: U.Pump("P-101", reference="PFD-100"),
        lambda: U.Column("T-101", reference="PFD-100"),
        lambda: U.Instrument("FT", 101, reference="PFD-100"),
    ],
)
def test_an_off_page_reference_on_equipment_is_refused(unit):
    with pytest.raises(ValueError) as excinfo:
        unit()
    assert "Feed or Product" in str(excinfo.value)


@pytest.mark.parametrize(
    ("cls", "args"),
    [
        (U.Block, ("B-1", 1, 1, "default", 120)),
        (U.Feed, ("F-1", "default", 40)),
        (U.Reducer, ("R-1", "default", 40)),
        (U.Instrument, ("PI", 101, "default", 40)),
    ],
)
def test_a_unit_option_given_by_position_is_refused(cls, args):
    """Check that a size given by position raises rather than filling another keyword."""
    with pytest.raises(TypeError, match="positional argument"):
        cls(*args)


def test_a_unit_that_restates_no_option_still_takes_them_by_position():
    """Check that a class on the base constructor keeps its positional size."""
    assert U.Pump("P-1", "default", 40).width == 40


# The layer as API


def test_units_all_lists_every_public_unit_class():
    """Check that ``units.__all__`` lists every public unit class and no private base."""
    declared = {
        name
        for name, value in vars(U).items()
        if inspect.isclass(value)
        and issubclass(value, U.Unit)
        and value.__module__ == "pandid.units"
    }
    public = {name for name in declared if not name.startswith("_")}

    assert public == set(U.__all__)
    assert declared - public == {
        "_Boundary",
        "_NormallyPositioned",
        "_MultiPortVessel",
        "_FaceFamilies",
        "_FluidMover",
        "_VariantPorted",
    }


def test_every_unit_class_is_on_the_package():
    """Check that every unit class is exported from the package as the same class."""
    import pandid

    for name in U.__all__:
        assert getattr(pandid, name) is getattr(U, name)
        assert name in pandid.__all__


def test_no_unit_class_shadows_the_package_s_own_names():
    """Check that no unit class name shadows the package's own names."""
    import pandid

    assert set(U.__all__).isdisjoint(
        {"Flowsheet", "Component", "SpecError", "units", "devices", "__version__"}
    )
    assert set(U.__all__).isdisjoint(pandid.devices.__all__)


def test_public_handle_exports_are_bound_to_their_classes():
    """Check that the returned handle types are exported from the package root."""
    import pandid

    handles = {
        "Component": "components",
        "Flowsheet": "flowsheet",
        "SpecError": "spec",
        "Port": "ports",
        "Stream": "streams",
        "Pin": "geometry",
        "Frame": "geometry",
        "Route": "geometry",
        "Loop": "loops",
        "ControlLoop": "loops",
        "ValveStation": "stations",
        "Issue": "validate",
        "TitleBlock": "document",
        "Revision": "document",
        "Annotation": "document",
        "TableBox": "document",
    }
    for name, module in handles.items():
        assert name in pandid.__all__
        assert getattr(pandid, name) is getattr(import_module(f"pandid.{module}"), name)
