"""The port annotations and the ports themselves must say the same thing.

Every unit class writes its nozzles down twice: once as the ``PORTS`` tuples (or
the ``__init__`` calls) that build them, and once as bare ``suction: Port``
annotations that let mypy and an editor see them. Two spellings of one fact
drift, and this suite is what stops them: it walks every ``Unit`` subclass the
package defines, builds one, and checks the two halves against each other in
both directions.

Found rather than listed, so a class added tomorrow is covered without anyone
remembering to come here. The exemptions are named, and there are only four
kinds, each argued at the class or the module it applies to:

- the **numbered members** of a variable-sized family (``Mixer``'s ``in_1`` ...
  ``in_n``, ``Splitter``'s ``out_1`` ... ``out_n``, both of ``Block``'s, the
  ``feed_1`` ... ``feed_n`` a second feed spells a ``Column``, ``Reactor`` or
  ``Separator`` with, and the ``draw_1`` ... ``draw_n`` a second draw spells a
  ``Column`` with -- the one class with *two* independent counted families),
  whose count is the caller's, so there is no finite set of names a class
  annotation could stand for one at a time.

  It is *only* the members. The family itself is perfectly declarable as a
  sequence -- ``inlets: tuple[Port, ...]`` -- and every one of them is
  declared, so the exemption is "this nozzle is reachable through a family the
  class declares" and not "this nozzle has a number on the end". A class cannot
  take it by naming a port ``thing_2``, and cannot use a family to get out of
  declaring a fixed nozzle: :func:`test_a_family_only_excuses_a_numbered_nozzle`
  is the ceiling and :func:`test_only_these_classes_declare_a_family` the floor;
- the **variant nozzles** (``HeatExchanger``'s ``bottoms``, ``Separator``'s
  ``overflow``), which belong to some variants and not others, so declaring them
  on the base class would tell a checker something false about every other one;
- the **superseded nozzles** of a class that replaces its base's whole nozzle
  list. All of these are :mod:`pandid.devices`'s generated classes --
  ``PlateExchanger`` has lettered sides and no shell, ``CheckValve`` has no
  actuator -- inheriting an annotation their base wrote for a nozzle they do
  not build, because Python has no way to un-declare one.
  ``__annotations__`` is merged down the MRO and there is no "delete", and
  re-annotating the name with something narrower is an incompatible
  override. So the phantom check answers for the annotations a class
  *writes*, and :func:`test_only_these_classes_supersede_a_declaration` is
  what keeps that from spreading past the eleven classes it is true of.

  ``units.Absorber`` and ``units.Stripper`` used to be here too, for the
  same reason: hand-written next to :class:`~pandid.units.Column`,
  inheriting four nozzles they do not build. #400 is why they are not
  anymore -- ``Column`` no longer declares those four at all, so there is
  nothing left for either class to inherit falsely. That is the fix this
  whole exemption exists to make unnecessary: a class the hierarchy tells
  the truth about needs no annotation-level patch;
- an **aliased nozzle** -- ``Reactor.feed``/``Column.feed``/``Separator.feed``,
  a bare name
  set beside ``feed_1`` in ``__init__`` rather than registered as a
  second port, so a one-feed vessel keeps the singular spelling without
  a ``PortSeries`` counting it twice (:func:`_family_aliases`). Found the
  same way the family exemption is: a name only counts if it really is a
  live attribute reaching a real member of a declared family, not a
  fixed list of classes.
"""

import ast
import inspect
import pathlib
import re

import pytest

from pandid import devices, units
from pandid.ports import Port

# A nozzle whose name ends in an underscore and a number is one member of a
# family sized at construction (Mixer(n_inlets=...), Splitter(n_outlets=...),
# Column/Reactor(n_feeds=...)). A class annotation is a statement about every
# instance of the class and the count is not in the type, so no annotation can
# name one. This is the *ceiling* on what a declared family may excuse, not the
# exemption itself: the exemption is membership, and it is checked by asking the
# family. See test_a_family_only_excuses_a_numbered_nozzle.
_NUMBERED = re.compile(r"_\d+$")


def _is_family(hint):
    """Whether ``hint`` is ``tuple[Port, ...]``, however this Python spells it.

    ``tuple[Port, ...]`` and nothing looser is what a family is declared as: a
    ``Sequence[Port]`` would let a class hand back a live view that changed
    under the caller, and the point of the declaration is that it is the ports,
    in order, as they are.

    Compared by origin and arguments rather than by ``==`` against the alias,
    because two readers evaluate these strings -- ``typing.get_type_hints`` and
    ``inspect.get_annotations`` -- across five Python versions, and this is what
    keeps the answer the same if either ever normalises ``tuple[...]`` into
    ``typing.Tuple[...]`` on the way out.
    """
    import typing

    return typing.get_origin(hint) is tuple and typing.get_args(hint) == (Port, Ellipsis)


# Every class that declares one, and what it calls it. Written down rather than
# derived so that adding a sixth is a deliberate act with this comment to read
# first, exactly as the old class-level list was.
#
# ``Column``, ``Reactor`` and ``Separator`` are here where they were absent from
# the list this replaces: they default to *one* feed, a real nozzle named
# ``feed_1`` the way
# every other count is, plus the bare ``feed`` alias :func:`_family_aliases`
# answers for. ``feeds`` is the one-tuple holding the real member either way,
# and is the same accessor once ``n_feeds`` spells the family ``feed_1`` ...
# ``feed_n``. The sequence is the general form; the alias is a convenience on
# top of it, not a second one.
#
# ``Block`` declares two and nothing else, since a block flow diagram's box has
# no nozzle every block has: *all* of its connections are one of the families.
#
# ``Column`` declares two of its own -- ``feeds`` and ``draws`` -- the one
# class in this dict that does, since it is the one class with two
# independent counted families (``n_feeds=`` and ``n_draws=``). See
# ``_EXACT_ARITY`` below for the typed side of that.
#
# ``Tank`` and ``Vessel`` each declare two as well -- ``inlets`` and
# ``outlets``, :class:`~pandid.units.Block`'s own pair -- but unlike
# ``Column`` only one of the two gets a typed side below: ``outputs=``
# above one is the untyped case, on the same trade ``Absorber`` and
# ``Stripper`` already take for ``Column``'s own ``n_draws``.
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


def _unit_classes():
    """Every ``Unit`` subclass the package defines, transitively.

    Filtered to ``pandid``'s own modules, because a test module that subclasses
    ``Unit`` to exercise the custom-unit workflow (``tests/test_custom_units.py``
    does, and the docs tell users to) is a fixture, not part of the shipped API,
    and pytest has already imported it by the time this runs.
    """
    found: dict[type, None] = {}
    pending = [units.Unit]
    while pending:
        cls = pending.pop()
        if cls in found or not cls.__module__.startswith("pandid."):
            continue
        found[cls] = None
        pending.extend(cls.__subclasses__())
    return list(found)


def _annotated(cls):
    """The nozzle names ``cls`` declares, its own and its bases'."""
    # get_type_hints, not __annotations__: units.py has `from __future__ import
    # annotations`, so every annotation is a string until something evaluates
    # it, and only get_type_hints walks the MRO and resolves each base's
    # strings against the module that wrote them. Comparing `is Port` rather
    # than by name is what keeps `kind: str`, `PORTS: list[...]` and the layout
    # engine's `_slot` out of the answer.
    import typing

    return {name for name, hint in typing.get_type_hints(cls).items() if hint is Port}


def _superseded(cls):
    """Annotations ``cls`` inherits for nozzles its own ``PORTS`` replaced.

    A class that declares ``PORTS`` replaces its base's list outright, which is
    what :meth:`~pandid.units.Unit._declared_ports` means by "the nearest
    declaration is the whole list". The base's *annotations* do not go with it,
    because nothing in Python removes an inherited one -- so these are the names
    a checker still resolves and a runtime lookup no longer finds.

    Read off the class's *own* annotations rather than ``get_type_hints``, which
    merges the MRO; that is what tells "written here" from "inherited", and it
    is why the exemption cannot leak to a class that simply forgot to declare a
    nozzle it builds.

    Subtracts :func:`_family_aliases` too, or ``Absorber``/``Stripper``/
    ``DistillationColumn``/``StirredTankReactor`` -- every generated or
    hand-written class with its own ``PORTS`` that inherits ``Reactor`` or
    ``Column`` -- would read as superseding the ``feed`` alias they never
    wrote and do not need to: it is not stale, it still resolves, and a
    class that declares no ``PORTS`` of its own is never asked the question
    at all.
    """
    if "PORTS" not in vars(cls):
        return set()
    return _annotated(cls) - _own_annotated(cls) - _built(cls) - _family_aliases(cls)


def _own_annotations(cls):
    """The annotations written in ``cls``'s own body, resolved.

    ``inspect.get_annotations`` and not ``cls.__dict__["__annotations__"]``,
    because where a class keeps them is a 3.10-through-3.14 difference and this
    package supports all five: PEP 649 made them lazy in 3.14, so the dict holds
    an ``__annotate_func__`` until something asks. This asks. It is also the one
    reader that answers for a single class rather than for the whole MRO, which
    is the distinction the exemption above turns on.
    """
    return inspect.get_annotations(cls, eval_str=True)


def _own_annotated(cls):
    """The nozzle names ``cls`` declares in its own body."""
    return {name for name, hint in _own_annotations(cls).items() if hint is Port}


def _families(cls):
    """The family accessors ``cls`` declares, its own and its bases'."""
    import typing

    return {name for name, hint in typing.get_type_hints(cls).items() if _is_family(hint)}


def _own_families(cls):
    """The family accessors written in ``cls``'s own body.

    The MRO is not wanted here: ``devices.StirredTankReactor`` inherits
    ``Reactor``'s ``feeds`` and its ``__init__`` builds one, which is right and
    is not a sixth declaration. Only a class that writes the annotation has
    decided anything.
    """
    return {name for name, hint in _own_annotations(cls).items() if _is_family(hint)}


def _family_members(cls):
    """The nozzle names one default instance reaches through its families.

    Built rather than matched against a naming rule, for the reason the classes
    build the tuples that way: asking the object is the only reader that cannot
    disagree with the constructor about who is in the family.
    """
    unit = cls("X-1")
    return {port.name for name in _families(cls) for port in getattr(unit, name)}


def _family_aliases(cls):
    """Annotated names that are a plain attribute alias for a family
    member, not a second port -- ``Reactor.feed``/``Column.feed`` for
    ``feed_1``, set beside it in ``__init__`` rather than registered a
    second time. Registering it too would give a ``PortSeries`` two
    names matching one nozzle and it would spread a family of one down
    the shell as if it had two members, so ``feed`` is deliberately
    absent from ``.ports`` -- present on the object, annotated on the
    class, and never *built* in :func:`_built`'s sense.

    Found rather than listed, the way :func:`_unit_classes` is: a name
    counts only if it really is a live attribute pointing at a real
    member of a family the class declares, so a class that does this
    trick tomorrow needs no entry added here, and an annotation with no
    runtime backing at all still falls through to the phantom it is.
    """
    unit = cls("X-1")
    members = _family_members(cls)
    return {
        name
        for name in _annotated(cls) - _built(cls)
        if isinstance(getattr(unit, name, None), Port) and getattr(unit, name).name in members
    }


def _built(cls):
    """The nozzle names one default instance of ``cls`` actually has.

    Every unit takes its name as the first positional argument (an Instrument's
    is its tag, a Tee's is optional), so one call constructs any of them, and
    the default of every other argument is what "default construction" means
    here: the variant, and the feed/inlet/outlet count, that a user gets by
    naming the class and nothing else.
    """
    return set(cls("X-1").ports)


@pytest.mark.parametrize("cls", _unit_classes(), ids=lambda c: c.__name__)
def test_every_port_built_is_annotated(cls):
    """A nozzle the class creates is a nozzle a type checker can see.

    The direction that catches the omission: someone adds a nozzle to ``PORTS``
    and the attribute stays invisible to mypy, which is the state this whole
    layer exists to leave behind.

    Two ways to be seen, and the second is the narrow exemption the module
    docstring describes: the nozzle is declared by name, or it is a member of a
    family the class declares as ``tuple[Port, ...]``. Nothing else counts, so a
    numbered name on its own no longer buys silence.
    """
    missing = _built(cls) - _annotated(cls) - _family_members(cls)
    assert not missing, (
        f"{cls.__name__} builds {sorted(missing)} but does not declare "
        f"them; add `{sorted(missing)[0]}: Port` to the class body"
    )


@pytest.mark.parametrize("cls", _unit_classes(), ids=lambda c: c.__name__)
def test_a_family_only_excuses_a_numbered_nozzle(cls):
    """A family is not a way out of declaring a fixed nozzle.

    The ceiling on the exemption above. ``inlets: tuple[Port, ...]`` covers
    ``in_1`` ... ``in_n``, whose count is the caller's and which therefore have
    no annotation available to them; a nozzle every instance has does have one,
    and putting it in a family instead would hide it from an editor's completion
    behind a subscript. ``Column("T-1").feed_1`` is the case worth stating: it
    is a real member of ``feeds`` *and* declared by name on ``Column1``, because
    a one-feed tower really has it -- the bare ``feed`` beside it is a different
    exemption again, :func:`_family_aliases`', since it is not itself built.
    """
    undeclared = {name for name in _built(cls) - _annotated(cls) if not _NUMBERED.search(name)}
    assert not undeclared, (
        f"{cls.__name__} reaches {sorted(undeclared)} only through a family, but "
        f"a nozzle whose name is not the caller's can be declared; add "
        f"`{sorted(undeclared)[0]}: Port` to the class body as well"
    )


@pytest.mark.parametrize("cls", _unit_classes(), ids=lambda c: c.__name__)
def test_every_annotation_is_a_port_that_is_built(cls):
    """A declared nozzle is one default construction really produces.

    The direction that catches the lie, and the reason ``Separator`` stops at
    ``feed``/``vapor``/``liquid`` and ``HeatExchanger`` at the shell and tube
    four: annotating a variant's nozzle here would promise it on every instance
    of the class, and mypy would then wave through a sheet that raises the
    moment it is drawn.
    """
    phantom = _annotated(cls) - _built(cls) - _superseded(cls) - _family_aliases(cls)
    assert not phantom, (
        f"{cls.__name__} declares {sorted(phantom)}, which a default "
        f"{cls.__name__} does not have; a nozzle only some variants carry "
        f"belongs on a per-variant subclass, not here"
    )


#: The classes whose numbered nozzles a type checker is allowed to answer for
#: with a blanket ``__getattr__``, at the price of that class's own typo
#: detection. ``Block`` alone, and only because its two counts are independent
#: and its usual declaration form -- ``inputs=["W", "W", "N"]`` -- carries no
#: length in its type, so the per-arity overloads the other families use would
#: need a class per (inputs, outputs) pair and would still miss the list form.
_CHECKER_VISIBLE_GETATTR = {"Block"}

#: The families answered *exactly* instead: a literal count picks an overload
#: returning a subclass that declares those nozzles and no others, so
#: ``Mixer("M", n_inlets=3).in_4`` is an error and so is ``.outlt``. Maps each
#: class to a tuple of the families *it* generates, one ``(keyword, member,
#: suffix)`` per family:
#:
#: - ``keyword`` is the constructor argument that sets the count
#:   (``n_inlets``, ``n_draws``, ...);
#: - ``member`` is the nozzle stem the count numbers (``in`` builds ``in_1``
#:   ... ``in_n``);
#: - ``suffix`` is what sits between the class name and the arity in the
#:   generated class's own name -- ``""`` for ``Mixer3``, and ``"Draw"`` for
#:   ``ColumnDraw3``, which is what tells the two families on one class apart
#:   without a second dict alongside this one.
#:
#: Every class here carries one family but ``Column``, which carries two:
#: ``n_feeds`` (suffix ``""``, the ordinary case a plain ``Column`` always
#: had) and ``n_draws`` (suffix ``"Draw"``, added beside it). The two are
#: independent rather than crossed -- see ``Column.__new__``'s own comment --
#: so ``feed``'s per-arity classes and ``draw``'s are two separate walks over
#: 1..8, not one walk over 64 combinations.
#:
#: ``Reactor`` is here despite ``StirredTankReactor`` adding ``duty``,
#: ``outlet`` and ``vent``: all three are already declared on ``Reactor`` too
#: (``set(devices.StirredTankReactor.__annotations__) -
#: set(units.Reactor.__annotations__)`` is empty), so narrowing ``Reactor``'s
#: own ``__new__`` to ``Reactor2`` loses nothing a stirred tank has. What a
#: narrower *base* return type would still break is the subclass's own
#: assignability -- ``t: StirredTankReactor = StirredTankReactor("R")`` wants
#: ``StirredTankReactor``, not ``Reactor2`` -- so ``scripts/gen_devices.py``
#: gives every generated subclass of a family base its own overloads and its
#: own ``ClassNameN`` classes rather than reusing the base's; see that
#: script's ``arity_family``.
#:
#: ``Absorber``, ``Stripper`` and ``DistillationColumn`` are here for
#: ``n_feeds`` only. All three still *take* ``n_draws=``/``draw_stages=``
#: at run time -- they are ``Column``'s own keywords and none of the three
#: subclasses overrides ``__init__`` -- but none gets a second overload
#: family of its own for it: copying ``Column``'s two-family trade onto
#: every narrower-or-wider subclass too would spend the class-explosion
#: problem a second, a third and a fourth time for a combination narrower
#: still than the one ``Column`` already declines to cross-type. So
#: ``absorber.draw_2`` does not resolve even where ``n_draws=2`` really
#: built it; ``absorber.draws[i]`` or ``absorber.port("draw_2")`` is the
#: typed route there, exactly as ``m.inlets[i]`` is for a *computed*
#: ``n_inlets`` everywhere else in this table.
#:
#: ``Separator`` carries one family and crosses nothing, unlike ``Column``:
#: which *draws* a separator has is fixed by its ``variant=`` rather than by
#: a count, so there is no second arity to pair ``n_feeds`` with. Its
#: ``variant="horizontal"`` refuses a second feed outright (see
#: ``Separator._ONE_FEED_VARIANTS``), which is a run-time refusal and not
#: something these overloads can express: the classes below are built at the
#: default variant, which is the one every arity really has.
#:
#: ``Tank`` and ``Vessel`` are here for ``inputs`` only, on the same
#: trade: both default to one outlet, so ``outputs=`` above one is the
#: combination this table declines to cross-type, exactly as
#: ``Absorber``'s ``n_draws`` is. ``tank.outlets[i]`` /
#: ``tank.port("out_2")`` is the typed route there.
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
    """``_EXACT_ARITY`` flattened to one row per (class, family).

    Most classes contribute one row; ``Column`` contributes two. Parametrizing
    over this, rather than over ``_EXACT_ARITY`` itself, is what lets the tests
    below walk ``n_feeds`` and ``n_draws`` as the two independent families they
    are instead of assuming there is exactly one keyword per class.
    """
    return [
        (cls, keyword, member, suffix)
        for cls, families in _EXACT_ARITY.items()
        for keyword, member, suffix in families
    ]


def _classes_with_a_visible_getattr():
    """Every class in ``units.py`` defining ``__getattr__`` under ``TYPE_CHECKING``.

    Read off the source rather than the objects, and it has to be: the whole
    point of ``if TYPE_CHECKING`` is that the method does not exist at run time,
    so there is nothing on the class to find. The AST is what a checker sees.
    """
    tree = ast.parse(pathlib.Path(units.__file__).read_text(encoding="utf-8"))
    out = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for stmt in node.body:
            # ``if TYPE_CHECKING:`` -- the guard that makes it visible to a
            # checker and absent at run time. ``if not TYPE_CHECKING`` is the
            # opposite and is how ``Unit`` hides the real one; the ``ast.Not``
            # test below is what tells the two apart.
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
    """A blanket ``__getattr__`` costs a class its typos; one may spend it.

    A class with a visible ``__getattr__`` answers for *every* attribute asked
    of it, so ``block.outlt`` is not caught at edit time. Only ``Block`` pays
    that, and only because the per-arity overloads the other three families use
    cannot be written for it: its two counts are independent, and the form its
    own examples are written in -- ``inputs=["W", "W", "N"]`` -- is a ``list``,
    whose length is not in its type.

    The run-time ``Unit.__getattr__`` still raises on the first access with
    every real nozzle listed, so a typo is loud rather than silent, just later.
    """
    assert _classes_with_a_visible_getattr() == _CHECKER_VISIBLE_GETATTR


@pytest.mark.parametrize(
    "cls,keyword,member,suffix",
    _arity_families(),
    ids=[f"{cls.__name__}-{keyword}" for cls, keyword, member, suffix in _arity_families()],
)
def test_a_literal_count_gets_a_class_declaring_exactly_those_nozzles(cls, keyword, member, suffix):
    """The per-arity subclasses say what the constructor really builds.

    ``Mixer3`` exists so a checker handed ``n_inlets=3`` can resolve ``in_3``
    and refuse ``in_4``. That is only true while the declarations match what
    ``__init__`` actually adds, and nothing else checks it -- the classes are
    under ``if TYPE_CHECKING`` and never run, so a wrong one is invisible until
    somebody writes the nozzle and is told it does not exist.

    So: build the unit for real at each arity, and compare its ports against
    what the subclass of that arity declares. ``ColumnDraw1`` is the case
    worth having: a one-draw tower's ``draw`` is *not* the base class's job,
    because ``n_draws`` defaults to zero and nothing can say a plain
    ``Column`` has one, so ``ColumnDraw1`` declares it itself rather than
    inheriting it -- unlike ``feed``, whose bare spelling is on ``Column``
    regardless of arity (see :func:`_family_aliases`) and so never appears
    in ``declared`` here at all, only ``feed_1`` does.
    """
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
        # Every nozzle this family builds at this arity -- the numbered
        # member included at every count, unlike the old single-family
        # version of this check, whose n=1 built the bare name instead.
        # What the arity class has to declare on its own is only the part
        # the base class does not already promise: subtracting
        # ``_annotated(cls)`` leaves ``Column1`` with just ``feed_1``
        # (``feed`` is on ``Column`` itself, as the alias, and is not in
        # ``built`` to begin with) and ``ColumnDraw1`` with ``draw`` (on
        # neither ``Column`` nor any base of it), from the one formula.
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
    """The ceiling: a subclass nobody's overload names is a lie nobody catches.

    ``Mixer9`` sitting in the file would declare nine inlets and never be
    handed to anyone, and the test above -- which walks ``1 .. _MAX_ARITY`` --
    would not look at it. ``ColumnDraw9`` is the same shape of leftover for
    ``Column``'s second family.
    """
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
    """The base class must keep hiding its own, or the three above are moot.

    ``Unit.__getattr__`` visible would answer for every unit class in the
    package and there would be no typo detection anywhere -- which is the state
    this whole module exists to prevent.
    """
    # It must exist at run time -- that is the method that raises with every
    # real nozzle listed, and it is the only reason a typo on one of the three
    # classes above is loud rather than silent.
    assert "__getattr__" in vars(units.Unit)

    # And it must be the guarded one. ``if not TYPE_CHECKING`` parses as a
    # unary ``not`` over the name, which is exactly what tells it apart from
    # the ``if TYPE_CHECKING`` the three classes use.
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
    """Nobody else may quietly grow a variable-sized nozzle family.

    The floor under the exemption. A family is what lets numbered nozzles exist
    at all here, so a new class with them has to declare one, and naming the
    five that do makes adding a sixth a deliberate act with the module docstring
    to read first. Keyed on the annotation a class *writes*, so a generated
    subclass inheriting ``Reactor``'s ``feeds`` is not a sixth decision.
    """
    declared = {cls: _own_families(cls) for cls in _unit_classes() if _own_families(cls)}
    assert declared == _DECLARED_FAMILIES


@pytest.mark.parametrize(
    "cls", sorted(_DECLARED_FAMILIES, key=lambda c: c.__name__), ids=lambda c: c.__name__
)
def test_a_declared_family_is_this_unit_s_own_ports_in_order(cls):
    """The other direction, and the one the declaration would otherwise lie in.

    ``inlets: tuple[Port, ...]`` is a promise about three separate things, and a
    checker can see none of them: that the attribute exists at all, that what is
    in it are this unit's ports rather than copies or names, and that the order
    is the order the nozzles were declared in -- which is the order the artwork
    spreads them down the face, so a family out of order would draw a sheet
    whose second inlet is the third one on the shell.

    **Soundness, not completeness.** Everything asserted here is of the form
    "what is in the tuple belongs there", so a family that fell *behind* the
    ports -- a nozzle added to ``__init__`` and not to the tuple -- passes this
    and is caught by :func:`test_every_port_built_is_annotated` instead, where
    it shows up as a port with no declaration of any kind. That check builds at
    the default arity only, so
    ``tests/test_units.py::test_a_family_is_every_numbered_nozzle_at_a_count_nothing_defaults_to``
    is what says the same thing at a count nothing defaults to. Three tests, and
    it is worth knowing which one holds which half.
    """
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
    """The generated classes whose base annotates a nozzle they do not build.

    Listed rather than counted, because each one is a checker resolving an
    attribute that raises at runtime, and that is the cost of the layer stated
    outright. Two shapes of it, and no others:

    - the six separators that draw off ``overflow``/``underflow`` where
      ``Separator`` annotates ``vapor``/``liquid``;
    - the four exchangers whose sides are not a shell and tubes, plus
      ``CheckValve``, which has no actuator to declare.

    A name appearing here that is not one of those is a nozzle somebody dropped,
    not a vocabulary somebody replaced.
    """
    superseded = {
        cls.__name__: sorted(_superseded(cls)) for cls in _unit_classes() if _superseded(cls)
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
    """The direction the exemption above must not weaken.

    A generated class declares ``PORTS``, so the phantom check stops asking
    about what it inherited -- which would be a hole if it were also allowed to
    inherit the annotations for the nozzles it *does* build. It is not: every
    one of them is written in the class body, which is what makes the emitted
    file readable as the declaration it is.
    """
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
    """The variant nozzles are real, and are still reached by name at runtime.

    Stated separately from the two invariants above because it is the *reason*
    for the second one, and because it is what the follow-up change (a generated
    subclass per variant) has to satisfy: these names move onto those classes,
    and this test is where it will show.
    """
    assert nozzle in cls("X-1", variant=variant).ports
    assert nozzle not in _annotated(cls)


@pytest.mark.parametrize("cls", _unit_classes(), ids=lambda c: c.__name__)
def test_annotations_bind_nothing(cls):
    """The declarations are annotations, never assignments.

    An annotation with a value would put a shared ``Port`` on the class, which
    every instance would then see until ``_add_port``'s ``setattr`` shadowed it,
    and a unit that failed to build one would silently answer with another
    unit's nozzle. Nothing about construction or the drawn sheet may change
    because of this layer, and this is the line that says so.

    The families are held to the same rule, and a shared default would be worse
    there: ``inlets = ()`` on the class is a plausible-looking mistake that
    makes a mixer whose ``__init__`` never ran answer "no inlets" instead of
    raising.
    """
    bound = {name for name in _annotated(cls) | _families(cls) if name in vars(cls)}
    assert not bound, f"{cls.__name__} assigns {sorted(bound)} instead of only annotating"
