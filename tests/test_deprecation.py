"""The deprecation mechanism: one declaration, a warning and a finding.

Exercised through a deprecated API declared *here*, not by deprecating something
real. The mechanism ships before its customers (#136, #138, #154, the
``sig_in``/``sig_out`` rename), and a test that leaned on one of those would
start failing on the day that spelling was deleted -- one release after it was
added -- which is the wrong thing for a test of the machinery to be tied to.
"""

import warnings

import pytest

from pandid import Flowsheet, devices as D, units as U
from pandid.deprecation import CODE, Deprecation, declarations

# Every DeprecationWarning raised in this file is one this file deliberately
# caused. Unfiltered they are the entire warnings summary of `pytest -q`, which
# is a summary worth keeping empty so that a real one stands out. The tests that
# are *about* the warning assert on it through `pytest.warns`, which installs a
# filter of its own and is unaffected by this.
pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


#: The stand-in. Written the way a real one is: a module constant beside the
#: code that honours it, naming a call an author types and the call that
#: replaces it.
RETIRED = Deprecation(
    what="Pump(cooled=True)",
    instead="Pump(jacket='cooling')",
    removed_in="99.0.0",
)


class _OldPump(U.Pump):
    """A pump built the retired way, so a whole sheet can be drawn with one."""

    def __init__(self, name, **kwargs):
        super().__init__(name, **kwargs)
        RETIRED.warn(self, where=name)


def _sheet():
    fs = Flowsheet("deprecated")
    feed = fs.add(U.Feed("F"))
    pump = fs.add(_OldPump("P-101"))
    prod = fs.add(U.Product("P"))
    fs.connect(feed.outlet, pump.suction)
    fs.connect(pump.discharge, prod.inlet)
    return fs, pump


# --- both signals, from one declaration --------------------------------------


def test_a_deprecated_call_warns():
    with pytest.warns(DeprecationWarning) as caught:
        _OldPump("P-101")
    assert len(caught) == 1


def test_a_deprecated_call_reports():
    fs, _ = _sheet()
    found = [i for i in fs.validate() if i.code == CODE]
    assert len(found) == 1
    assert found[0].severity == "warning"


def test_the_warning_and_the_finding_are_the_same_sentence():
    """The one thing the whole mechanism exists to guarantee.

    Not two constructors compared: the string a filter would show, captured off
    a real call, against the string ``validate()`` reports for that same call.
    An edit that changed one and not the other fails here.
    """
    fs = Flowsheet("same")
    with pytest.warns(DeprecationWarning) as caught:
        fs.add(_OldPump("P-101"))
    warned = str(caught[0].message)
    reported = [i for i in fs.validate() if i.code == CODE]
    assert [warned] == [i.message for i in reported]


def test_the_message_names_the_replacement_and_the_release():
    fs, _ = _sheet()
    message = next(i for i in fs.validate() if i.code == CODE).message
    assert "P-101" in message  # what to edit
    assert "Pump(cooled=True)" in message  # what is going
    assert "Pump(jacket='cooling')" in message  # what replaces it
    assert "99.0.0" in message  # when it goes


def test_the_warning_points_at_the_callers_line():
    """stacklevel: the author's file, not pandid's."""
    with pytest.warns(DeprecationWarning) as caught:
        _OldPump("P-101")
    assert caught[0].filename == __file__


# --- carried from construction to validate() ---------------------------------


def test_a_unit_deprecated_before_add_is_still_reported():
    """The case the mechanism is shaped around.

    The call happens while the unit is being built, when there is no flowsheet
    in scope to record against, and the finding still reaches ``validate()``.
    """
    pump = _OldPump("P-101")
    assert pump.flowsheet is None
    fs = Flowsheet("late")
    fs.add(pump)
    assert [i.code for i in fs.validate()] == [CODE]


def test_a_unit_never_added_is_not_reported():
    _OldPump("P-101")  # built, warned, and left off the sheet
    fs = Flowsheet("empty")
    assert [i for i in fs.validate() if i.code == CODE] == []


def test_it_survives_a_render():
    """``fs.warnings`` is what ``render()`` leaves behind, so it has to be in it."""
    fs, _ = _sheet()
    fs.to_svg()
    assert [i.code for i in fs.warnings if i.code == CODE] == [CODE]


def test_reporting_does_not_consume_the_finding():
    """``validate()`` reports; it never clears. Twice must answer twice."""
    fs, _ = _sheet()
    first = [i.message for i in fs.validate() if i.code == CODE]
    second = [i.message for i in fs.validate() if i.code == CODE]
    assert first == second != []


# --- the carriers ------------------------------------------------------------


def test_each_unit_reports_for_itself():
    """Two units, two findings: two places in the author's file to edit."""
    fs = Flowsheet("two")
    fs.add(_OldPump("P-101"))
    fs.add(_OldPump("P-102"))
    found = sorted(i.message for i in fs.validate() if i.code == CODE)
    assert len(found) == 2
    assert "P-101" in found[0] and "P-102" in found[1]


def test_one_carrier_says_it_once():
    """A repeat is one thing to fix, so it is one finding -- and still warns."""
    fs = Flowsheet("repeat")
    pump = fs.add(_OldPump("P-101"))
    with pytest.warns(DeprecationWarning) as caught:
        RETIRED.warn(pump, where=pump.name)
        RETIRED.warn(pump, where=pump.name)
    assert len(caught) == 2
    assert len([i for i in fs.validate() if i.code == CODE]) == 1


def test_a_stream_carries_one():
    fs = Flowsheet("stream")
    feed = fs.add(U.Feed("F"))
    prod = fs.add(U.Product("P"))
    stream = fs.connect(feed.outlet, prod.inlet)
    with pytest.warns(DeprecationWarning):
        RETIRED.warn(stream, where=stream.name)
    assert len([i for i in fs.validate() if i.code == CODE]) == 1


def test_the_flowsheet_carries_one():
    """For a deprecated ``Flowsheet`` method, which has the sheet and no unit."""
    fs = Flowsheet("sheet")
    with pytest.warns(DeprecationWarning):
        RETIRED.warn(fs)
    assert len([i for i in fs.validate() if i.code == CODE]) == 1


def test_a_loop_carries_one():
    fs = Flowsheet("loop")
    loop = fs.add_loop("F", 303)
    with pytest.warns(DeprecationWarning):
        RETIRED.warn(loop, where=loop.name)
    assert len([i for i in fs.validate() if i.code == CODE]) == 1


# --- one sheet's finding is only ever that sheet's ---------------------------


def test_a_deprecation_needs_a_carrier():
    """#207: there is no home for a finding with nothing to ride on.

    There was one -- a process-wide list, appended to every ``validate()`` for
    the life of the interpreter -- and a sheet built in one Jupyter cell
    reported a call made in another. Refusing the call is what closes it: each
    of these three used to record, and the second is the one a customer writes
    by accident, passing a ``flowsheet`` that is still ``None``.
    """
    for nothing in ((), (None,), (object(),)):
        with pytest.raises(TypeError, match="carrier"):
            RETIRED.warn(*nothing)


def test_a_refused_call_does_not_warn_either():
    """Both signals or neither. A finding nothing will report is a bug in the
    caller, not something to half-announce."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises(TypeError):
            RETIRED.warn(None)
    assert caught == []


def test_a_deprecation_stays_on_the_sheet_that_made_it():
    """#207, end to end: a second sheet in the same process sees none of it.

    Through the stand-in, because 0.1.3 ships no deprecation of its own -- the
    six 0.1.2 declared were deleted in it, which is the one-release rule
    working rather than a gap in this file.
    """
    used = Flowsheet("used")
    feed = used.add(U.Feed("F"))
    pump = used.add(_OldPump("P-101"))
    prod = used.add(U.Product("P"))
    used.connect(feed.outlet, pump.suction)

    with pytest.warns(DeprecationWarning) as caught:
        RETIRED.warn(prod, where=prod.name)
        RETIRED.warn(used)
    warned = sorted(str(w.message) for w in caught)
    assert len(warned) == 2

    reported = sorted(i.message for i in used.validate() if i.code == CODE)
    assert reported == sorted([*warned, RETIRED.message("P-101")])

    untouched = Flowsheet("untouched")
    assert [i for i in untouched.validate() if i.code == CODE] == []


# --- said once, and not lost -------------------------------------------------


def test_two_carriers_with_the_same_sentence_both_report():
    """The dedupe is per carrier, not per sentence.

    Two units are two places in the author's file to edit even when the finding
    reads identically, which it does when the call names no ``where``. A
    mechanism that deduplicated on the sentence would report one and drop one.
    """
    fs = Flowsheet("twins")
    first = fs.add(U.Pump("P-101"))
    second = fs.add(U.Pump("P-102"))
    with pytest.warns(DeprecationWarning):
        RETIRED.warn(first)
        RETIRED.warn(second)
    assert len([i for i in fs.validate() if i.code == CODE]) == 2


def test_a_second_render_says_it_once_too():
    """``render()`` assigns ``fs.warnings`` rather than appending to it, so a
    sheet drawn twice reports what it found once, not twice."""
    fs, _ = _sheet()
    fs.to_svg()
    fs.to_svg()
    assert [i.code for i in fs.warnings if i.code == CODE] == [CODE]


# --- the declaration ---------------------------------------------------------


def test_a_declaration_needs_all_three_parts():
    for missing in ({"what": ""}, {"instead": ""}, {"removed_in": " "}):
        kwargs = {"what": "a()", "instead": "b()", "removed_in": "9.9.9", **missing}
        with pytest.raises(ValueError, match="Deprecation needs"):
            Deprecation(**kwargs)


def test_where_is_optional():
    """A deprecation with nothing on the sheet to name still reads."""
    assert RETIRED.message() == (
        "Pump(cooled=True) is deprecated and is removed in pandid 99.0.0; "
        "use Pump(jacket='cooling')"
    )


def test_a_replacement_that_is_not_a_drop_in_says_so_before_it_is_named():
    """ "Use X instead" is a promise, and a promise about a *different* drawing
    has to be kept out loud.

    The caveat goes in the middle rather than at the end, so the sentence still
    finishes on the line the author types next -- which is the whole reason the
    replacement comes last.
    """
    moved = Deprecation(
        what="Pump(cooled=True)",
        instead="Pump(jacket='cooling')",
        removed_in="99.0.0",
        note="the drawing changes -- a jacket band round the casing",
    )
    assert moved.message("P-101") == (
        "P-101: Pump(cooled=True) is deprecated and is removed in pandid 99.0.0; "
        "the drawing changes -- a jacket band round the casing, "
        "so use Pump(jacket='cooling')"
    )


#: Every declaration the package makes, beside the two calls it is about, so a
#: test can put the drawings side by side. Written out rather than built by
#: evaluating ``what`` and ``instead``: those strings exist for an author to
#: find in their own file, and turning them back into calls would test that a
#: sentence round-trips rather than that it is true.
_RETIRED_PAIRS = [
    (
        U.VESSEL_VARIANT_LEGS,
        lambda: U.Vessel("D-1", variant="legs"),
        lambda: U.Vessel("D-1", supports="leg"),
    ),
    (
        U.VESSEL_VARIANT_SKIRTED,
        lambda: U.Vessel("D-1", variant="skirted"),
        lambda: U.Vessel("D-1", supports="skirt"),
    ),
    (
        U.REACTOR_VARIANT_PLAIN,
        lambda: U.Reactor("R-1", variant="plain"),
        lambda: U.Reactor("R-1", internals="packing"),
    ),
    (
        U.SEPARATOR_VARIANT_GRAVITY,
        lambda: U.Separator("V-1", variant="gravity"),
        lambda: U.Separator("V-1", characteristic="gravity"),
    ),
    (
        U.SEPARATOR_VARIANT_ELECTROSTATIC,
        lambda: U.Separator("V-1", variant="electrostatic"),
        lambda: U.Separator("V-1", characteristic="electrostatic"),
    ),
    (
        U.SEPARATOR_VARIANT_ELECTROMAGNETIC,
        lambda: U.Separator("V-1", variant="electromagnetic"),
        lambda: U.Separator("V-1", characteristic="electromagnetic"),
    ),
]


def _drawing(make):
    """One call's whole drawing: the artwork and the box it is drawn in."""
    from pandid.render.symbols import default_registry

    symbol = default_registry.for_unit(make())
    return symbol.svg, symbol.width, symbol.height


@pytest.mark.parametrize(
    ("declared", "before", "after"), _RETIRED_PAIRS, ids=[d.what for d, _, _ in _RETIRED_PAIRS]
)
def test_a_declaration_carries_a_note_exactly_where_the_drawing_moves(declared, before, after):
    """An empty note is a claim, not an absence: it says the replacement draws
    what the old spelling drew.

    So the two are held to each other. Three of the six really are drop-ins --
    a separator's characteristic resolves to byte-identical artwork whichever
    word asks for it -- and three move the sheet, because ``variant=`` drew its
    support or its bed into the body and the keyword puts an ISO part on the
    standard shell instead. A deprecation that silently changed the drawing is
    the failure this is here to stop, and it stays stopped for a seventh.
    """
    moved = _drawing(before) != _drawing(after)
    assert bool(declared.note) == moved, (
        f"{declared.what}: the drawing "
        f"{'moves' if moved else 'does not move'}, so the note should be "
        f"{'filled in' if moved else 'empty'}"
    )


def test_every_declaration_is_in_the_table_above():
    """The pairs are hand-written, so a seventh declaration has to be added to
    them rather than skipped by them."""
    assert {id(d) for d, _, _ in _RETIRED_PAIRS} == {id(d) for d in declarations().values()}


def test_no_deprecation_has_outlived_its_release():
    """The one-release rule, enforced instead of remembered.

    Every deprecation the package declares names a release that has not shipped.
    One that names the current version or an older one should have been deleted
    in that release, and this is what says so before a user finds it still
    there. The six 0.1.2 declared are what it walked through the gate; 0.1.3
    deleted them and declares none of its own.
    """
    from pandid import __version__

    def release(text):
        return tuple(int(part) for part in text.split("."))

    now = release(__version__)
    overdue = {
        where: dep.removed_in
        for where, dep in declarations().items()
        if release(dep.removed_in) <= now
    }
    assert overdue == {}, (
        f"deprecated spellings past the release that was to delete them "
        f"(pandid {__version__}): {overdue}"
    )


def test_declarations_finds_a_module_constant():
    """The walker itself, against a module declaring one the way a real one is.

    ``declarations()`` walks :mod:`pandid` and this module is not in it, so the
    same recognition is done here on this module's own namespace: a constant of
    this type, found by walking what a module holds.
    """
    import sys

    module = sys.modules[__name__]
    found = {name: value for name, value in vars(module).items() if isinstance(value, Deprecation)}
    assert found == {"RETIRED": RETIRED}


def test_the_package_declares_exactly_the_variant_keywords_it_is_retiring():
    """Six spellings, all one retirement: a ``variant=`` that named a *part*
    rather than a body, moved to the keyword that names the part.

    Spelled out rather than counted. A deprecation is a promise to delete
    something one release later, and the list of what has been promised is the
    thing a release has to be read against -- so a seventh arriving has to be
    added here, and one quietly disappearing fails.
    """
    assert {name.rsplit(".", 1)[-1] for name in declarations()} == {
        "VESSEL_VARIANT_LEGS",
        "VESSEL_VARIANT_SKIRTED",
        "REACTOR_VARIANT_PLAIN",
        "SEPARATOR_VARIANT_GRAVITY",
        "SEPARATOR_VARIANT_ELECTROSTATIC",
        "SEPARATOR_VARIANT_ELECTROMAGNETIC",
    }


# --- a warning is about the word the author wrote ----------------------------


#: The two convenience classes whose ``VARIANT_ALIASES`` map ``default`` onto a
#: retired spelling, with the ``Separator`` variant each resolves to. They are
#: the only place in the package where what an author wrote and what the unit
#: ends up carrying can differ *across a deprecation*, so they are what the
#: guard has to be checked against.
ALIASED_TO_A_RETIRED_VARIANT = [
    (D.GravitySeparator, "gravity"),
    (D.ElectrostaticPrecipitator, "electrostatic"),
]


@pytest.mark.parametrize(
    "cls,resolved",
    ALIASED_TO_A_RETIRED_VARIANT,
    ids=[c.__name__ for c, _ in ALIASED_TO_A_RETIRED_VARIANT],
)
def test_a_convenience_class_is_not_told_off_for_a_word_it_wrote_for_you(cls, resolved):
    """``GravitySeparator("V-1")`` names no variant at all.

    ``VARIANT_ALIASES`` then maps ``default`` onto ``gravity`` -- which is the
    class's whole job -- and the unit carries the resolved spelling from there
    on. Reading *that* to decide whether to warn asked the wrong question: it
    scolded an author for a word the class had written on their behalf, and
    told them to swap the class they had deliberately picked for
    ``Separator(characteristic='gravity')``, which draws the same symbol with
    the wrong nozzle names.

    The drawing is unaffected either way, which is what made it quiet: the unit
    still resolves to the same variant and the same characteristic.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        unit = cls("V-1")
    assert [w for w in caught if issubclass(w.category, DeprecationWarning)] == []
    assert unit.variant == resolved
    assert unit.characteristic == resolved


@pytest.mark.parametrize(
    "cls,resolved",
    ALIASED_TO_A_RETIRED_VARIANT,
    ids=[c.__name__ for c, _ in ALIASED_TO_A_RETIRED_VARIANT],
)
def test_the_retired_spelling_still_warns_on_the_class_it_was_retired_on(cls, resolved):
    """The other direction, and the one that makes the fix a fix rather than a
    deletion: ``Separator(variant="gravity")`` is exactly what was retired, and
    it still says so.

    Typed on the convenience class it warns too, because the author still typed
    the retired word -- what the guard now refuses to do is invent it for them.
    """
    with pytest.warns(DeprecationWarning, match=f"Separator\\(variant='{resolved}'\\)"):
        U.Separator("V-1", variant=resolved)
    with pytest.warns(DeprecationWarning, match=f"Separator\\(variant='{resolved}'\\)"):
        cls("V-1", variant=resolved)


@pytest.mark.parametrize(
    "cls,resolved",
    ALIASED_TO_A_RETIRED_VARIANT,
    ids=[c.__name__ for c, _ in ALIASED_TO_A_RETIRED_VARIANT],
)
def test_the_keyword_that_replaces_it_is_silent_too(cls, resolved):
    """The spelling the warning recommends must not itself warn, or the advice
    is a loop. Checked here rather than assumed, since it goes through the same
    guard by the other branch."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        U.Separator("V-1", characteristic=resolved)
    assert [w for w in caught if issubclass(w.category, DeprecationWarning)] == []


def test_a_silenced_class_reports_nothing_on_a_sheet_either():
    """The warning and the ``validate()`` finding are one declaration, so a
    convenience class that has stopped warning must have stopped reporting --
    otherwise the sheet still carries the scolding the author never earned."""
    fs = Flowsheet("aliased")
    fs.add(D.GravitySeparator("V-1"))
    fs.add(D.ElectrostaticPrecipitator("V-2"))
    assert [f for f in fs.validate() if f.code == CODE] == []


def test_the_cyclone_is_not_among_them():
    """``Separator(variant="cyclone")`` is the one drawing in group 8 that ISO
    14617-1 §4.5 names by registration number as a symbol in its own right, and
    group 29 has no vortex to compose one from. It is not a body plus a mark,
    so there is no keyword to move it to and nothing to deprecate."""
    assert not [d for d in declarations().values() if "cyclone" in d.what]
