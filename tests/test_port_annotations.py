"""Check that each unit class's port annotations and the ports it builds agree."""

import ast
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
    return _annotated(cls) - _own_annotated(cls) - _built(cls) - _family_aliases(cls)


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


@pytest.mark.parametrize("cls", _shipped_unit_classes(), ids=lambda c: c.__name__)
def test_every_port_built_is_annotated(cls):
    """Check that every port built is annotated."""
    missing = _built(cls) - _annotated(cls) - _family_members(cls)
    assert not missing, (
        f"{cls.__name__} builds {sorted(missing)} but does not declare "
        f"them; add `{sorted(missing)[0]}: Port` to the class body"
    )


@pytest.mark.parametrize("cls", _shipped_unit_classes(), ids=lambda c: c.__name__)
def test_a_family_only_excuses_a_numbered_nozzle(cls):
    """Check that a family only excuses a numbered nozzle."""
    undeclared = {name for name in _built(cls) - _annotated(cls) if not _NUMBERED.search(name)}
    assert not undeclared, (
        f"{cls.__name__} reaches {sorted(undeclared)} only through a family, but "
        f"a nozzle whose name is not the caller's can be declared; add "
        f"`{sorted(undeclared)[0]}: Port` to the class body as well"
    )


@pytest.mark.parametrize("cls", _shipped_unit_classes(), ids=lambda c: c.__name__)
def test_every_annotation_is_a_port_that_is_built(cls):
    """Check that every annotation is a port that is built."""
    phantom = _annotated(cls) - _built(cls) - _superseded(cls) - _family_aliases(cls)
    assert not phantom, (
        f"{cls.__name__} declares {sorted(phantom)}, which a default "
        f"{cls.__name__} does not have; a nozzle only some variants carry "
        f"belongs on a per-variant subclass, not here"
    )


#: Classes whose numbered nozzles a checker-visible ``__getattr__`` answers for.
_CHECKER_VISIBLE_GETATTR = {"Block"}

#: Families answered by per-arity classes: class -> ((keyword, member, name suffix), ...).
_EXACT_ARITY = {
    units.Mixer: (("n_inlets", "in", ""),),
    units.Splitter: (("n_outlets", "out", ""),),
    units.Column: (("n_feeds", "feed", ""), ("n_draws", "draw", "Draw")),
    units.Reactor: (("n_feeds", "feed", ""),),
    units.Separator: (("n_feeds", "feed", ""),),
    units.Absorber: (("n_feeds", "feed", ""),),
    units.Stripper: (("n_feeds", "feed", ""),),
    units.DistillationColumn: (("n_feeds", "feed", ""),),
    units.Tank: (("inputs", "in", ""),),
    units.Vessel: (("inputs", "in", ""),),
}
_MAX_ARITY = 8


def _arity_families():
    """Return ``_EXACT_ARITY`` flattened to one row per (class, family)."""
    return [
        (cls, keyword, member, suffix)
        for cls, families in _EXACT_ARITY.items()
        for keyword, member, suffix in families
    ]


def _classes_with_a_visible_getattr():
    """Return every class in ``units.py`` defining ``__getattr__`` under ``TYPE_CHECKING``."""
    tree = ast.parse(pathlib.Path(units.__file__).read_text(encoding="utf-8"))
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


@pytest.mark.parametrize(
    "cls,keyword,member,suffix",
    _arity_families(),
    ids=[f"{cls.__name__}-{keyword}" for cls, keyword, member, suffix in _arity_families()],
)
def test_a_literal_count_gets_a_class_declaring_exactly_those_nozzles(cls, keyword, member, suffix):
    """Check that a literal count gets a class declaring exactly those nozzles."""
    module = ast.parse(pathlib.Path(units.__file__).read_text(encoding="utf-8"))
    declared = {
        node.name: {
            stmt.target.id
            for stmt in node.body
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
        }
        for node in ast.walk(module)
        if isinstance(node, ast.ClassDef)
    }
    for n in range(1, _MAX_ARITY + 1):
        name = f"{cls.__name__}{suffix}{n}"
        assert name in declared, f"{name} is not defined; the overload names it"
        # The nozzles this arity builds, less those the base class already declares.
        built = {
            port
            for port in cls("X-1", **{keyword: n}).ports
            if re.fullmatch(rf"{member}(_\d+)?", port)
        }
        expected = built - _annotated(cls)
        assert declared[name] == expected, (
            f"{name} declares {sorted(declared[name])} but a {keyword}={n} "
            f"{cls.__name__} builds {sorted(expected)} beyond what {cls.__name__} "
            f"itself already declares"
        )


def test_no_arity_class_is_left_over(cls=None):
    """Check that no arity class is left over."""
    module = ast.parse(pathlib.Path(units.__file__).read_text(encoding="utf-8"))
    expected = {
        f"{cls.__name__}{suffix}{n}"
        for cls, keyword, member, suffix in _arity_families()
        for n in range(1, _MAX_ARITY + 1)
    }
    found = {
        node.name
        for node in ast.walk(module)
        if isinstance(node, ast.ClassDef)
        and re.fullmatch(
            r"(Mixer|Splitter|ColumnDraw|Column|Reactor|Separator|Block|Absorber"
            r"|Stripper|DistillationColumn|Tank|Vessel)\d+",
            node.name,
        )
    }
    assert found == expected


def test_the_run_time_getattr_stays_hidden_from_checkers():
    """Check that the run-time ``__getattr__`` stays hidden from checkers."""
    # It must exist at run time, where it raises with every real nozzle listed.
    assert "__getattr__" in vars(units.Unit)

    # And it must be the ``if not TYPE_CHECKING`` one.
    tree = ast.parse(pathlib.Path(units.__file__).read_text(encoding="utf-8"))
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
    assert guarded == ["Unit"], (
        f"expected Unit alone to hide a run-time __getattr__ from checkers, got {guarded}"
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
        "PlateExchanger": ["shell_in", "shell_out", "tube_in", "tube_out"],
        "SpiralExchanger": ["shell_in", "shell_out", "tube_in", "tube_out"],
        "ThinFilmEvaporator": ["shell_in", "shell_out", "tube_in", "tube_out"],
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


@pytest.mark.parametrize("cls", _shipped_unit_classes(), ids=lambda c: c.__name__)
def test_annotations_bind_nothing(cls):
    """Check that annotations bind nothing."""
    bound = {name for name in _annotated(cls) | _families(cls) if name in vars(cls)}
    assert not bound, f"{cls.__name__} assigns {sorted(bound)} instead of only annotating"
