"""The deprecation mechanism: one declaration, a warning and a finding.

Exercised through a deprecated API declared *here*, not by deprecating something
real. The mechanism ships before its customers (#136, #138, #154, the
``sig_in``/``sig_out`` rename), and a test that leaned on one of those would
start failing on the day that spelling was deleted -- one release after it was
added -- which is the wrong thing for a test of the machinery to be tied to.
"""

import warnings

import pytest

from pandid import Flowsheet, units as U
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


def test_the_shipped_deprecations_stay_on_the_sheet_that_made_them():
    """All three 0.1.2 ships, end to end, and a second sheet that sees none.

    The real ones rather than the stand-in, because #207 is about what a
    process holding more than one sheet reports. Held to a count and to the
    sentences the warnings carried, not to spellings written out here, so the
    release that deletes them thins this test rather than reddening it.
    """
    used = Flowsheet("used")
    feed = used.add(U.Feed("F"))
    cyclone = used.add(U.Separator("CY-401", variant="cyclone"))
    prod = used.add(U.Product("P"))
    used.connect(feed.outlet, cyclone.feed)
    used.connect(cyclone.overflow, prod.inlet)

    with pytest.warns(DeprecationWarning) as caught:
        cyclone.vapor  # -> .overflow
        cyclone.liquid  # -> .underflow
        used.add(U.Valve("CV-303", variant="pneumatic"))  # -> variant='control'
    warned = sorted(str(w.message) for w in caught)
    assert len(warned) == 3

    reported = sorted(i.message for i in used.validate() if i.code == CODE)
    assert reported == warned

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


def test_no_deprecation_has_outlived_its_release():
    """The one-release rule, enforced instead of remembered.

    Every deprecation the package declares names a release that has not shipped.
    One that names the current version or an older one should have been deleted
    in that release, and this is what says so before a user finds it still
    there. It stopped being vacuous when #138 retired the dust collectors' phase
    draws, which are the first declarations to walk through this gate.
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
    """The walker itself, proved twice over.

    Against this module, whose stand-in is declared the way a real one is; and
    against ``pandid``, which now has real ones to find. The first is what makes
    the test able to fail on its own terms -- a package that declared none could
    not show that a declaration *would* be found -- and the second is what says
    the walker reaches the package it is pointed at.
    """
    import sys

    module = sys.modules[__name__]
    found = {name: value for name, value in vars(module).items() if isinstance(value, Deprecation)}
    assert found == {"RETIRED": RETIRED}

    # Keyed by where each is reachable from, so a constant imported into a
    # second module appears twice. Asserted by suffix for that reason.
    declared = declarations()
    assert declared, "the walker found nothing in a package that declares some"
    assert {where.rsplit(".", 1)[1] for where in declared} == {
        "_RETIRED_VAPOR_DRAW",
        "_RETIRED_LIQUID_DRAW",
        "_RETIRED_PNEUMATIC",
        "_RETIRED_PANEL",
        "_RETIRED_AUX",
        "_RETIRED_ON",
    }
