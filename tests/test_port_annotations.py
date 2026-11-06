"""Check that each unit class's port annotations and the ports it builds agree."""

import ast
import functools
import inspect
import pathlib
import re

import pytest

from pandid import devices, units
from pandid.ports import Port
from test_placement import _shipped_unit_classes

# A numbered member of a family sized at construction, such as ``in_3``.
_NUMBERED = re.compile(r"_\d+$")


def _is_family(hint):
    """Return whether ``hint`` is ``tuple[Port, ...]``, however this Python spells it."""
    import typing

    return typing.get_origin(hint) is tuple and typing.get_args(hint) == (Port, Ellipsis)


# The classes that declare a family, and the family accessors each declares.
_DECLARED_FAMILIES = {
    units.Mixer: {"inlets"},
    units.Splitter: {"outlets"},
    units.Block: {"inlets", "outlets"},
    units.Column: {"feeds", "draws"},
    units.Reactor: {"feeds"},
    units.Separator: {"feeds"},
    units.Tank: {"inlets", "outlets"},
    units.Vessel: {"inlets", "outlets"},
}


def _annotated(cls):
    """Return the nozzle names ``cls`` declares, its own and its bases'."""
    # get_type_hints resolves every base's string annotations against its own module.
    import typing

    return {name for name, hint in typing.get_type_hints(cls).items() if hint is Port}


def _superseded(cls):
    """Return annotations ``cls`` inherits for nozzles its own ``PORTS`` replaced."""
    if "PORTS" not in vars(cls):
        return set()
    return _annotated(cls) - _own_annotated(cls) - _built(cls) - _family_aliases(cls) - _ranged(cls)


def _own_annotations(cls):
    """Return the annotations written in ``cls``'s own body, resolved."""
    return inspect.get_annotations(cls, eval_str=True)


def _own_annotated(cls):
    """Return the nozzle names ``cls`` declares in its own body."""
    return {name for name, hint in _own_annotations(cls).items() if hint is Port}


def _families(cls):
    """Return the family accessors ``cls`` declares, its own and its bases'."""
    import typing

    return {name for name, hint in typing.get_type_hints(cls).items() if _is_family(hint)}


def _own_families(cls):
    """Return the family accessors written in ``cls``'s own body."""
    return {name for name, hint in _own_annotations(cls).items() if _is_family(hint)}


def _family_members(cls):
    """Return the nozzle names one default instance reaches through its families."""
    unit = cls("X-1")
    return {port.name for name in _families(cls) for port in getattr(unit, name)}


def _family_aliases(cls):
    """Return annotated names that alias a member of a declared family."""
    unit = cls("X-1")
    members = _family_members(cls)
    return {
        name
        for name in _annotated(cls) - _built(cls)
        if isinstance(getattr(unit, name, None), Port) and getattr(unit, name).name in members
    }


def _built(cls):
    """Return the nozzle names one default instance of ``cls`` actually has."""
    return set(cls("X-1").ports)


#: Each family base and the keywords that set its counts.
_COUNTS = {
    units.Mixer: ("n_inlets",),
    units.Splitter: ("n_outlets",),
    units.Reactor: ("n_feeds",),
    units.Separator: ("n_feeds",),
    units.Column: ("n_feeds", "n_draws"),
    units.Tank: ("inputs",),
    units.Vessel: ("inputs",),
}
#: The highest count the numbered annotations cover.
_MAX_COUNT = 8


@functools.cache
def _counted(base):
    """Return the nozzles a count up to ``_MAX_COUNT`` adds to a default ``base``."""
    return {
        port
        for keyword in _COUNTS[base]
        for n in range(1, _MAX_COUNT + 1)
        for port in base("X-1", **{keyword: n}).ports
    } - _built(base)


def _ranged(cls):
    """Return the nozzles a count adds on the family bases of ``cls``."""
    return set().union(*(_counted(base) for base in cls.__mro__ if base in _COUNTS))


@pytest.mark.parametrize("cls", _shipped_unit_classes(), ids=lambda c: c.__name__)
def test_the_annotations_are_the_ports_built_and_bind_nothing(cls):
    """Check that every port built is annotated, every annotation is built, and none binds."""
    built, annotated = _built(cls), _annotated(cls)
    missing = built - annotated - _family_members(cls)
    assert not missing, (
        f"{cls.__name__} builds {sorted(missing)} but does not declare "
        f"them; add `{sorted(missing)[0]}: Port` to the class body"
    )
    # A family only excuses a numbered nozzle.
    undeclared = {name for name in built - annotated if not _NUMBERED.search(name)}
    assert not undeclared, (
        f"{cls.__name__} reaches {sorted(undeclared)} only through a family, but "
        f"a nozzle whose name is not the caller's can be declared; add "
        f"`{sorted(undeclared)[0]}: Port` to the class body as well"
    )
    phantom = annotated - built - _superseded(cls) - _family_aliases(cls) - _ranged(cls)
    assert not phantom, (
        f"{cls.__name__} declares {sorted(phantom)}, which a default "
        f"{cls.__name__} does not have; a nozzle only some variants carry "
        f"belongs on a per-variant subclass, not here"
    )
    bound = {name for name in annotated | _families(cls) if name in vars(cls)}
    assert not bound, f"{cls.__name__} assigns {sorted(bound)} instead of only annotating"


@pytest.mark.parametrize("base", _COUNTS, ids=lambda c: c.__name__)
def test_a_family_base_declares_every_nozzle_a_count_builds(base):
    """Check that a family base declares every nozzle a count up to the highest builds."""
    missing = _counted(base) - _own_annotated(base)
    assert not missing, f"{base.__name__} does not declare {sorted(missing)}"


#: Classes whose numbered nozzles a checker-visible ``__getattr__`` answers for.
_CHECKER_VISIBLE_GETATTR = {"Block"}


def _parsed(module):
    """Return the syntax tree of ``module``'s source."""
    return ast.parse(pathlib.Path(module.__file__).read_text(encoding="utf-8"))


def _classes_with_a_visible_getattr():
    """Return every class in ``units.py`` defining ``__getattr__`` under ``TYPE_CHECKING``."""
    tree = _parsed(units)
    out = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for stmt in node.body:
            # ``if TYPE_CHECKING:`` makes the method visible to a checker and absent at run time.
            if (
                isinstance(stmt, ast.If)
                and isinstance(stmt.test, ast.Name)
                and stmt.test.id == "TYPE_CHECKING"
                and any(
                    isinstance(b, ast.FunctionDef) and b.name == "__getattr__" for b in stmt.body
                )
            ):
                out.add(node.name)
    return out


def test_only_these_classes_answer_for_a_numbered_nozzle():
    """Check that only these classes answer for a numbered nozzle."""
    assert _classes_with_a_visible_getattr() == _CHECKER_VISIBLE_GETATTR


def test_the_run_time_getattr_stays_hidden_from_checkers():
    """Check that the run-time ``__getattr__`` stays hidden from checkers."""
    # It must exist at run time, where it raises with every real nozzle listed.
    assert "__getattr__" in vars(units.Unit)

    # And it must be the ``if not TYPE_CHECKING`` one.
    tree = _parsed(units)
    guarded = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
        for stmt in node.body
        if isinstance(stmt, ast.If)
        and isinstance(stmt.test, ast.UnaryOp)
        and isinstance(stmt.test.op, ast.Not)
        and isinstance(stmt.test.operand, ast.Name)
        and stmt.test.operand.id == "TYPE_CHECKING"
        and any(isinstance(b, ast.FunctionDef) and b.name == "__getattr__" for b in stmt.body)
    ]
    assert guarded == ["Unit", "Reactor"], (
        f"expected Unit and Reactor alone to hide a run-time __getattr__ from checkers, "
        f"got {guarded}"
    )


def test_only_these_classes_declare_a_family():
    """Check that only these classes declare a family."""
    declared = {cls: _own_families(cls) for cls in _shipped_unit_classes() if _own_families(cls)}
    assert declared == _DECLARED_FAMILIES


@pytest.mark.parametrize(
    "cls", sorted(_DECLARED_FAMILIES, key=lambda c: c.__name__), ids=lambda c: c.__name__
)
def test_a_declared_family_is_this_unit_s_own_ports_in_order(cls):
    """Check that a declared family is this unit's own ports, in order."""
    unit = cls("X-1")
    order = list(unit.ports)
    for name in _DECLARED_FAMILIES[cls]:
        family = getattr(unit, name)
        assert isinstance(family, tuple), f"{cls.__name__}.{name} is not a tuple"
        assert all(port is unit.ports[port.name] for port in family), (
            f"{cls.__name__}.{name} holds something other than this unit's own ports"
        )
        members = {id(port) for port in family}
        assert [port.name for port in family] == [
            n for n in order if id(unit.ports[n]) in members
        ], f"{cls.__name__}.{name} is not in declaration order"


def test_only_these_classes_supersede_a_declaration():
    """Check that only these classes supersede a declaration."""
    superseded = {
        cls.__name__: sorted(_superseded(cls))
        for cls in _shipped_unit_classes()
        if _superseded(cls)
    }
    assert superseded == {
        "Cyclone": ["liquid", "vapor"],
        "GravitySeparator": ["liquid", "vapor"],
        "ElectrostaticPrecipitator": ["liquid", "vapor"],
        "Screen": ["liquid", "vapor"],
        "ImpactSeparator": ["liquid", "vapor"],
        "MagneticSeparator": ["liquid", "vapor"],
        "AirCooledExchanger": ["shell_in", "shell_out"],
        "Bunker": ["vent"],
        "PlateExchanger": ["shell_in", "shell_out", "tube_in", "tube_out"],
        "SpiralExchanger": ["shell_in", "shell_out", "tube_in", "tube_out"],
        "ThinFilmEvaporator": ["shell_in", "shell_out", "tube_in", "tube_out"],
        "JacketedReactor": ["duty"],
        "CheckValve": ["actuator"],
    }


def test_every_generated_class_writes_its_own_nozzle_declarations():
    """Check that every generated class writes its own nozzle declarations."""
    for name in devices.__all__:
        cls = getattr(devices, name)
        assert {port for port, _, _ in cls.PORTS} <= _own_annotated(cls), (
            f"{name} builds nozzles it does not declare in its own body"
        )


@pytest.mark.parametrize(
    ("cls", "variant", "nozzle"),
    [
        (units.HeatExchanger, "kettle", "bottoms"),
        (units.Separator, "sifter", "overflow"),
        (units.Separator, "sifter", "underflow"),
        (units.HeatExchanger, "plate", "side_a_in"),
    ],
)
def test_variant_nozzles_exist_but_are_not_declared_on_the_base(cls, variant, nozzle):
    """Check that variant nozzles exist but are not declared on the base."""
    assert nozzle in cls("X-1", variant=variant).ports
    assert nozzle not in _annotated(cls)
