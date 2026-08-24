"""``pandid.devices``: the generated equipment classes, and what they promise.

Five promises, and this file is each of them:

1. the committed module is what the generator emits today, so a hand edit to it
   is caught rather than lost the next time anyone runs the script;
2. every registered ``(kind, variant)`` is claimed exactly once, so vendoring a
   stencil cannot quietly add a drawing nobody has said what to call;
3. every class's declared nozzles are ones its drawing actually anchors, and are
   visible to a type checker;
4. a sheet built from device classes round-trips through ``to_dict`` /
   ``from_dict``, which is where the four quiet integration edges in
   ``pandid.spec`` show up;
5. the two tables in ``docs/api.md`` still say what the registry says. A class
   nobody documented is a class nobody finds, which is the whole reason this
   layer exists.

The compatibility half -- that every shipped ``(kind, variant)`` pair still
builds and draws exactly what it always did -- is ``tests/test_variants.py``,
which sweeps the base classes and only the base classes. That sweep is 238
``(class, variant)`` cases over the 52 classes ``pandid.units`` defines, which
is more than the registry's 228 pairs rather than fewer: a kind with no artwork
still has ``"default"``, and a kind two classes own is swept once for each.
"""

import ast
import functools
import importlib.util
import pathlib
import re
import typing

import pytest

from pandid import Flowsheet, devices, portgeom, spec, units
from pandid.ports import Port
from pandid.render.symbols import default_registry

DEVICE_CLASSES = [getattr(devices, name) for name in devices.__all__]
IDS = [cls.__name__ for cls in DEVICE_CLASSES]


@functools.lru_cache(maxsize=None)
def _generator():
    """Import ``scripts/gen_devices.py`` by path.

    It is a dev-only script rather than part of the package, exactly as
    ``scripts/vendor_symbols.py`` is, and this is the same loader
    ``tests/test_symbol_invariants.py`` uses for that one.
    """
    path = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "gen_devices.py"
    module_spec = importlib.util.spec_from_file_location("_pandid_script_gen_devices", path)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# The generated file, against the generator that emits it
# ---------------------------------------------------------------------------


def test_the_committed_module_matches_the_generator():
    """A hand edit to devices.py is lost the next time anyone runs the generator.

    The same rule ``_vendored_symbols.py`` is held to, for the same reason: a
    stale generated file still imports and still draws, so nothing else notices.
    The difference is what the drift would be *about* -- there, artwork; here,
    which piece of equipment a drawing is.
    """
    generator = _generator()
    committed = generator.OUT.read_text(encoding="utf-8")
    if generator.render() != committed:
        pytest.fail(
            "pandid/devices.py is not what scripts/gen_devices.py emits today.\n"
            "It is regenerated wholesale, so a hand edit is lost the next time\n"
            "anyone runs the generator. Change the DEVICES, OWNS or\n"
            "STAYS_ON_BASE entry that produces it, then run\n\n"
            "    python scripts/gen_devices.py\n\n"
            "and commit the regenerated file with the change that caused it.",
            pytrace=False,
        )


def test_every_registered_symbol_is_claimed_exactly_once():
    """The anti-drift check, run against the live registry.

    ``claims()`` raises rather than returning on any of the three failures, so
    this is really an assertion that the generator's own gate is satisfied by
    the library as it stands: nothing registered is unclassified, nothing
    classified has lost its drawing, and no drawing is claimed twice.
    """
    claimed = _generator().claims()
    assert claimed.keys() == set(default_registry._symbols)


def test_the_generator_refuses_a_drawing_nobody_has_classified():
    """Vendor a stencil and this layer stops until someone says what it is.

    The failure the whole design exists to force. Faked by dropping a claim
    rather than by registering a symbol, because the registry is a module-level
    singleton and the two ways round are the same assertion.
    """
    generator = _generator()
    key, why = next(iter(generator.STAYS_ON_BASE.items()))
    del generator.STAYS_ON_BASE[key]
    try:
        with pytest.raises(SystemExit, match=f"{key[0]}/{key[1]}"):
            generator.claims()
    finally:
        generator.STAYS_ON_BASE[key] = why


def test_the_generator_refuses_two_claims_on_one_drawing():
    """A drawing is one device, so two classes claiming it is a question, not a fact."""
    generator = _generator()
    key = ("separator", "cyclone")
    generator.STAYS_ON_BASE[key] = "a second claim, for the test"
    try:
        with pytest.raises(SystemExit, match="two claims on one drawing"):
            generator.claims()
    finally:
        del generator.STAYS_ON_BASE[key]


@pytest.mark.parametrize("kind", ["instrument", "feed", "product"])
def test_the_generator_refuses_the_three_kinds_that_may_not_have_classes(kind):
    """Refused by name, because each would be *silently* wrong.

    An Instrument's variants are functions rather than devices, and
    ``_Boundary.repeats`` tests ``type(other) is type(self)``, which any
    subclass defeats without a word: a utility header tapped twice would be
    reported as two services the reader cannot tell apart.
    """
    generator = _generator()
    assert kind in generator.REFUSED_KINDS
    generator.DEVICES[(kind, "default")] = ("Bogus", "...")
    try:
        with pytest.raises(SystemExit, match=f"a {kind} may not have a class"):
            generator.claims()
    finally:
        del generator.DEVICES[(kind, "default")]


# ---------------------------------------------------------------------------
# What each class declares, against what its drawing anchors
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cls", DEVICE_CLASSES, ids=IDS)
def test_every_declared_nozzle_is_one_the_symbol_anchors(cls):
    """A nozzle the artwork does not place falls back to the centre of the box.

    Two of them then land on the same point and their streams stack, which is
    what makes this the check the renamed draws had to pass: ``Cyclone`` calls
    its draws ``overflow`` and ``underflow`` while its drawing still anchors
    ``vapor`` and ``liquid``, and only :attr:`~pandid.units.Unit.PORT_ANCHORS`
    joins the two.
    """
    unit = cls("X-1")
    unplaced = [name for name in unit.ports if not portgeom.is_anchored(unit, name)]
    assert unplaced == []


@pytest.mark.parametrize("cls", DEVICE_CLASSES, ids=IDS)
def test_every_variant_a_class_owns_anchors_the_same_nozzles(cls):
    """``PORTS`` is read once, so a class is one nozzle set across its drawings.

    A class owning two variants that anchor differently would be two devices
    sharing a name, and the second variant's user would meet it as a stream
    drawn to the middle of the equipment.

    ``PORTS`` is a subset of what is built rather than the whole of it, because
    a base whose ``__init__`` adds a nozzle by hand still does:
    ``StirredTankReactor`` declares the three fixed ones and ``Reactor``'s
    constructor lays down the charge nozzle on top, exactly as it does for its
    base. Restating that one in ``PORTS`` would hand ``_add_port`` a name it
    already has.
    """
    built = {variant: set(cls("X-1", variant=variant).ports) for variant in cls.VARIANTS}
    assert len(set(map(frozenset, built.values()))) == 1
    for variant, names in built.items():
        unit = cls("X-1", variant=variant)
        assert {port for port, _, _ in cls.PORTS} <= names
        assert all(portgeom.is_anchored(unit, name) for name in names)


@pytest.mark.parametrize("cls", DEVICE_CLASSES, ids=IDS)
def test_every_declared_nozzle_is_visible_to_a_type_checker(cls):
    """The half of this layer a test can only approximate.

    ``get_type_hints`` resolves what mypy resolves, so a nozzle missing here is
    one an editor cannot complete and a checker cannot answer for -- which is
    the state the whole change exists to leave behind. It says nothing about
    ``fs.add`` keeping the subclass; that is ``Flowsheet.add``'s TypeVar, and
    only a real checker run proves it.
    """
    declared = {name for name, _, _ in cls.PORTS}
    hints = typing.get_type_hints(cls)
    assert declared <= hints.keys()
    assert all(hints[name] is Port for name in declared)


def _family_device_classes():
    """Device classes whose base is a variable-port family -- ``StirredTankReactor``
    (:class:`~pandid.units.Reactor`) alone today, and whichever earns it next.

    Asked of the generator rather than named, for the reason
    ``tests/test_port_annotations.py``'s ``_EXACT_ARITY`` gives for ``Reactor``: a
    device that subclasses a family base tomorrow gets this test for free.
    """
    generator = _generator()
    return [cls for cls in DEVICE_CLASSES if generator.arity_family(cls.__mro__[1])]


_FAMILY_DEVICE_CLASSES = _family_device_classes()
_FAMILY_IDS = [cls.__name__ for cls in _FAMILY_DEVICE_CLASSES]


@pytest.mark.parametrize("cls", _FAMILY_DEVICE_CLASSES, ids=_FAMILY_IDS)
def test_a_generated_family_subclass_gets_its_own_exact_arity_classes(cls):
    """The mirror, for generated classes, of
    ``test_port_annotations.test_a_literal_count_gets_a_class_declaring_exactly_those_nozzles``.

    ``StirredTankReactor`` is the case there is today: a literal ``n_feeds`` has
    to resolve to *its own* arity class, ``StirredTankReactor2``, and not
    ``Reactor2`` -- a checker handed the base's class there would no longer
    consider the result a ``StirredTankReactor`` at all. This is what would miss
    a generator bug that ``test_the_committed_module_matches_the_generator``
    cannot: that test only compares the committed file against another run of
    the same generator, so a wrong ``emit()`` agrees with itself. This instead
    builds the real unit and checks its ports.
    """
    generator = _generator()
    keyword, member, _default, max_n = generator.arity_family(cls.__mro__[1])
    module = ast.parse(pathlib.Path(devices.__file__).read_text(encoding="utf-8"))
    declared = {
        node.name: {
            stmt.target.id
            for stmt in node.body
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
        }
        for node in ast.walk(module)
        if isinstance(node, ast.ClassDef)
    }
    for n in range(1, max_n + 1):
        name = f"{cls.__name__}{n}"
        assert name in declared, f"{name} is not defined; the overload names it"
        built = {
            port
            for port in cls("X-1", **{keyword: n}).ports
            if re.fullmatch(rf"{member}_\d+", port)
        }
        assert declared[name] == built, (
            f"{name} declares {sorted(declared[name])} but a {keyword}={n} "
            f"{cls.__name__} builds {sorted(built)}"
        )


@pytest.mark.parametrize("cls", DEVICE_CLASSES, ids=IDS)
def test_naming_a_class_alone_asks_for_that_class_s_drawing(cls):
    """``Cyclone("S-1")`` draws a cyclone, not the flash drum ``Separator`` defaults to.

    ``variant`` defaults to ``"default"``, so a class that names its variants and
    left that one out would refuse to be built by name at all. Listing it and
    aliasing it is the whole answer, and this is the assertion that it was done.
    """
    assert "default" in cls.VARIANTS
    assert (cls.kind, cls("X-1").variant) in default_registry._symbols


@pytest.mark.parametrize("cls", DEVICE_CLASSES, ids=IDS)
def test_a_class_refuses_a_drawing_another_device_owns(cls):
    """The refusal, with the low-level form the message has to offer.

    A variant this class does not draw belongs to some other device, and the
    base that owns the whole kind draws every one of them -- so the message is
    "ask for it this way" rather than "you cannot have this".
    """
    with pytest.raises(ValueError, match="belongs to whichever class draws it"):
        cls("X-1", variant="not_a_registered_variant")


# ---------------------------------------------------------------------------
# One drawing, one nozzle vocabulary
# ---------------------------------------------------------------------------


_COLLECTORS = [
    (devices.Cyclone, "cyclone"),
    (devices.GravitySeparator, "gravity"),
    (devices.ElectrostaticPrecipitator, "electrostatic"),
]


@pytest.mark.parametrize(("cls", "variant"), _COLLECTORS, ids=lambda x: getattr(x, "__name__", x))
def test_a_collector_draws_the_same_nozzles_whichever_way_it_was_built(cls, variant):
    """The whole of #138, in one assertion.

    These three collect *dust*, and their drawings have anchored the catch
    ``liquid`` since 0.1.0. The classes corrected it to ``underflow``; up to
    0.1.1 ``Separator(variant=...)`` did not, so one drawing answered to two
    vocabularies and which you got depended on which class you constructed.
    That was written down as permanent and is not, and this is where the two
    forms are held to one another.
    """
    assert set(cls("S-1").ports) == {"feed_1", "overflow", "underflow"}
    assert set(units.Separator("S-2", variant=variant).ports) == set(cls("S-3").ports)


@pytest.mark.parametrize(("cls", "variant"), _COLLECTORS, ids=lambda x: getattr(x, "__name__", x))
def test_a_renamed_draw_lands_where_the_drawing_puts_the_nozzle_it_renamed(cls, variant):
    """The rename is a name and nothing else: same point, same faces, same ink.

    Against the *artwork's* own names, which never changed: the stencils still
    anchor ``vapor`` and ``liquid``, and both spellings of the class reach them
    through ``Separator._VARIANT_ANCHORS``. A nozzle whose anchor went missing
    would fall back to the centre of the box, which is how this would show up as
    a moved drawing rather than as a failure here.
    """
    renamed = cls("S-1")
    low_level = units.Separator("S-2", variant=variant)
    symbol = default_registry.for_unit(renamed)
    for new, old in (("overflow", "vapor"), ("underflow", "liquid")):
        assert portgeom.port_faces(renamed, new) == portgeom.port_faces(low_level, new)
        assert renamed._symbol_anchor(new) == old
        assert old in symbol.ports


# ---------------------------------------------------------------------------
# pandid.spec: the four edges that break quietly
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cls", DEVICE_CLASSES, ids=IDS)
def test_a_device_round_trips_through_a_spec(cls):
    """``from_dict(to_dict(fs))`` for a sheet built from each class.

    The edge this covers is ``spec._CLASSES``, which was built from
    ``units.__all__`` alone: ``_write_unit`` writes ``type(unit).__name__``, so
    every one of these would have raised on the way *out*. It also covers the
    variant round trip, which is the reason a renamed variant lists both
    spellings: what is stored is the registry's name, so that is what the file
    carries and what the class has to accept when the file is read back.
    """
    sheet = Flowsheet("round trip")
    original = sheet.add(cls("X-1"))
    written = sheet.to_dict()
    read_back = Flowsheet.from_dict(written)

    rebuilt = read_back.units[0]
    assert type(rebuilt) is cls
    assert rebuilt.variant == original.variant
    assert list(rebuilt.ports) == list(original.ports)
    assert read_back.to_dict() == written


def test_a_spec_may_name_a_device_class_in_either_spelling():
    """The class name from the docs, and its snake_case spelling.

    Both, because a spec is hand-written and a reader who has seen
    ``devices.KettleReboiler`` and a reader who has seen ``kind: kettle_reboiler``
    are asking for the same thing.
    """
    for written in ("KettleReboiler", "kettle_reboiler", "KETTLEREBOILER"):
        sheet = Flowsheet.from_dict({"name": "s", "units": [{"kind": written, "name": "E-1"}]})
        assert type(sheet.units[0]) is devices.KettleReboiler


def test_a_kind_tag_still_names_the_class_that_owns_the_whole_kind():
    """The sharpest of the four edges.

    ``_ALIASES`` maps the internal ``kind`` tag onto a class name, and six of
    the 74 classes in ``pandid.devices`` carry ``kind == "pump"``. Built from both layers, ``kind:
    pump`` would mean whichever of them iterated last -- and the answer would
    move about as classes were added, which is the worst kind of quiet. It is
    built from ``units`` alone, so a kind tag names the class that draws every
    variant of that kind, exactly as it did before this layer existed.

    ``Absorber``, ``Stripper`` and ``DistillationColumn`` are the one place
    several ``units`` classes themselves share a ``kind`` -- all four are
    ``"column"``, the same as ``Column`` -- because none is a distinct
    drawing, only a narrower or wider port set on the one shell. ``kind:
    column`` still has to mean the class that draws every variant of it,
    which is ``Column`` and not the one of the four that happened to
    iterate last, so they are the named exception rather than the rule
    this test checks.
    """
    # Shares its kind with Column, and is not what a bare `kind: column`
    # should resolve to; see the docstring.
    shares_a_kind = {"Absorber", "Stripper", "DistillationColumn"}
    for name in units.__all__:
        if name == "Unit" or name in shares_a_kind:
            continue
        base = getattr(units, name)
        assert spec._ALIASES[base.kind] == name


def test_a_device_class_takes_the_arguments_its_base_declares():
    """``normal_position`` and ``fail`` on a valve device, ``n_feeds`` on a reactor.

    ``spec`` keys those arguments to the class that declares them, and it
    matched on the class *name*, so every device class would have been refused
    the argument its own constructor accepts -- a spec refusing to read back
    what it had just written.
    """
    sheet = Flowsheet.from_dict(
        {
            "name": "s",
            "units": [
                {"kind": "ControlValve", "name": "FV-101", "fail": "closed"},
                {"kind": "SpectacleBlind", "name": "SB-101", "normal_position": "closed"},
                {"kind": "StirredTankReactor", "name": "R-101", "n_feeds": 2},
            ],
        }
    )
    valve, blind, reactor = sheet.units
    assert valve.fail == "closed"
    assert blind.normal_position == "closed"
    assert {"feed_1", "feed_2"} <= set(reactor.ports)
    assert Flowsheet.from_dict(sheet.to_dict()).to_dict() == sheet.to_dict()


def test_an_instrument_is_still_refused_in_the_units_section():
    """No device class was generated for it, and the older refusal still fires."""
    assert not any(getattr(devices, name).kind == "instrument" for name in devices.__all__)
    with pytest.raises(spec.SpecError, match="instruments go in the top-level"):
        Flowsheet.from_dict({"name": "s", "units": [{"kind": "Instrument", "name": "FT-1"}]})


# ---------------------------------------------------------------------------
# The layer as API
# ---------------------------------------------------------------------------


def test_every_device_class_is_on_the_package():
    """``pandid.Cyclone`` and ``pandid.devices.Cyclone`` are one class.

    The star import in ``pandid/__init__.py`` takes its list from
    ``devices.__all__``, which the generator writes, so there is no second list
    to fall out of step.
    """
    import pandid

    for name in devices.__all__:
        assert getattr(pandid, name) is getattr(devices, name)
        assert name in pandid.__all__


def test_no_device_class_shadows_a_unit_class():
    """Both layers are re-exported from the package, so one name is one class."""
    assert set(devices.__all__).isdisjoint(units.__all__)


@pytest.mark.parametrize("cls", DEVICE_CLASSES, ids=IDS)
def test_every_device_is_a_subclass_of_the_class_that_owns_its_kind(cls):
    """Which is what keeps ``isinstance(u, units.Pump)`` true of a GearPump.

    ``pandid.document``, ``pandid.validate`` and ``spec._write_unit`` all ask
    that question, and a device layer that answered no would have needed each of
    them changed -- and would have left every third-party check quietly wrong.
    """
    base = next(
        getattr(units, name)
        for name in units.__all__
        if name != "Unit"
        and getattr(units, name).kind == cls.kind
        and not getattr(units, name).VARIANTS
    )
    assert issubclass(cls, base)
    assert cls.kind == base.kind


@pytest.mark.parametrize("cls", DEVICE_CLASSES, ids=IDS)
def test_every_device_draws(cls):
    """One unit of each class on a sheet, rendered. The end-to-end check.

    Everything above measures a declaration; this is the drawing it produces,
    and it is where a nozzle the artwork cannot place, an unregistered variant
    or a broken alias shows up as an exception rather than as an opinion.
    """
    sheet = Flowsheet(cls.__name__)
    sheet.add(cls("X-1"))
    assert "<svg" in sheet.to_svg()


# ---------------------------------------------------------------------------
# The two tables in docs/api.md
# ---------------------------------------------------------------------------

DOCS = pathlib.Path(__file__).resolve().parent.parent / "docs" / "api.md"
VARIANT = re.compile(r"`([a-z0-9_]+)`")
CLASS = re.compile(r"`([A-Z]\w+)`")
LOCAL_SPELLING = re.compile(r"\(as `[^`]+`\)")


def _table(heading):
    """The first markdown table under ``### heading``, as rows of stripped cells."""
    section = DOCS.read_text(encoding="utf-8").split(f"\n### {heading}\n", 1)[1]
    rows = []
    for line in section.splitlines():
        if line.startswith("|"):
            rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
        elif rows:
            break
    return [row for row in rows[1:] if not row[0].startswith("---")]


def _drawings(cell, kind):
    """The registered variants a row's last cell names.

    Class-local spellings are struck first, since ``DustCollector`` accepting
    ``belt`` for ``filter/gas_belt`` is not a claim on ``filter/belt``, which is
    a drawing of its own. Everything else backticked and not registered --
    ``normal_position``, ``large_end`` -- is prose, and drops out against the
    registry.
    """
    named = set(VARIANT.findall(LOCAL_SPELLING.sub("", cell)))
    return named & set(default_registry.variants(kind))


def test_the_equipment_class_table_matches_the_classes():
    """Generated here from the classes themselves, so the table cannot drift.

    A class the docs do not list is a class nobody finds by reading them, and
    the four columns are exactly what a reader is looking for: the name, the
    drawing's kind, what it inherits, and the nozzles it does not.
    """
    expected = []
    for cls in DEVICE_CLASSES:
        base = cls.__mro__[1]
        mine, theirs = list(cls("X-1").ports), list(base("X-1").ports)
        differs = [f"`+{name}`" for name in mine if name not in theirs]
        differs += [f"`-{name}`" for name in theirs if name not in mine]
        expected.append(
            [f"`{cls.__name__}`", f"`{cls.kind}`", f"`{base.__name__}`", " ".join(differs)]
        )
    assert _table("Equipment classes") == expected


def test_the_variants_table_gives_every_drawing_exactly_one_owner():
    """The other half: which class each of the registry's 228 drawings is reached
    by name as.

    The same accounting ``scripts/gen_devices.py`` refuses to run without, kept
    against the page rather than against the module, so vendoring a stencil
    fails here too until the docs say whose it is.
    """
    owner = {}
    for row in _table("Variants"):
        names = CLASS.findall(row[0])
        classes = [getattr(devices, name, None) or getattr(units, name) for name in names]
        if len(classes) == 1:
            assert row[1] == f"`{classes[0].kind}`", f"{names[0]}: wrong kind in the docs"
        for cls in classes:
            for variant in _drawings(row[2], cls.kind):
                assert (cls.kind, variant) not in owner, (
                    f"{cls.kind}/{variant} is claimed by both "
                    f"{owner[(cls.kind, variant)]} and {cls.__name__}"
                )
                owner[(cls.kind, variant)] = cls.__name__
    assert set(owner) == set(default_registry._symbols)
    for cls in DEVICE_CLASSES:
        listed = {variant for (_, variant), name in owner.items() if name == cls.__name__}
        assert listed == {cls.VARIANT_ALIASES.get(v, v) for v in cls.VARIANTS}


# ---------------------------------------------------------------------------
# The counts the prose quotes, against the registry that decides them
# ---------------------------------------------------------------------------

README = pathlib.Path(__file__).resolve().parent.parent / "README.md"


def _prose(path):
    """A page as one line, so a count that wrapped is still one match."""
    return " ".join(path.read_text(encoding="utf-8").split())


def _counts_in(path, pattern):
    """Every match of *pattern* on *path*, as a tuple of the integers in it.

    ``re.findall`` hands back a bare string for a one-group pattern and a tuple
    for the rest, so the single group is re-wrapped rather than iterated -- over
    a string, ``tuple(int(n) for n in m)`` counts digits.
    """
    found = re.findall(pattern, _prose(path))
    return [tuple(int(n) for n in (m if isinstance(m, tuple) else (m,))) for m in found]


def test_the_pages_quote_the_registry_they_are_describing():
    """README.md and docs/api.md state the size of the registry in prose, and
    prose does not recompute itself: `139 registered symbols` outlived two
    vendoring PRs on the front page of the project, and `docs/api.md` managed to
    say 27 and 41 about the same set of symbols in one document.

    So the four registry-derived numbers on those two pages are asserted here
    rather than reviewed. Each is matched on a distinctive phrase rather than on
    a bare integer, which is what keeps this from firing on a pressure or a
    pixel count that happens to be the same number.

    The size of the *example* corpus is not pinned this way. It is spelled as an
    English word ("the sixteen shipped examples") in a dozen docstrings whose
    sentences differ, and a regex over those is a worse thing to maintain than
    the sentences. That reasoning was wrong and #310 is what it cost: the
    spelled-out number went stale in every one of those docstrings at once and
    nothing failed. What holds the count honest is the other half of this
    sentence and only that half -- every corpus measurement is taken by a test
    over ``SCENARIOS``, which is built from the examples rather than from a
    literal -- so a sentence that quotes a corpus size beside its measurement
    is quoting something no test reads. Write the size only where a test
    asserts it.
    """
    symbols = default_registry.__dict__["_symbols"]
    gravity = sum(1 for s in symbols.values() if s.gravity_fixed)
    # A drawing "gets no class of its own" when the docs' own Variants table
    # hands it to a base class in pandid.units rather than to a device class.
    owner = {}
    for row in _table("Variants"):
        for name in CLASS.findall(row[0]):
            cls = getattr(devices, name, None) or getattr(units, name)
            for variant in _drawings(row[2], cls.kind):
                owner[(cls.kind, variant)] = name
    classless = sum(1 for name in owner.values() if name not in devices.__all__)

    assert _counts_in(README, r"\*\*(\d+) registered symbols\*\*") == [(len(symbols),)]
    assert _counts_in(README, r"(\d+) of the (\d+) registered drawings") == [
        (classless, len(symbols))
    ]
    assert _counts_in(DOCS, r"(\d+) of the (\d+) registered drawings") == [
        (classless, len(symbols))
    ]
    assert _counts_in(DOCS, r"(\d+) registered symbols carry `Symbol\.gravity_fixed`") == [
        (gravity,)
    ]
    assert _counts_in(DOCS, r"The (\d+) marked symbols") == [(gravity,)]
