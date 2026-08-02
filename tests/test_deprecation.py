"""The deprecation mechanism: one declaration, a warning and a finding.

Exercised through a deprecated API declared *here*, not by deprecating something
real. The mechanism ships before its customers (#136, #138, #154, the
``sig_in``/``sig_out`` rename), and a test that leaned on one of those would
start failing on the day that spelling was deleted -- one release after it was
added -- which is the wrong thing for a test of the machinery to be tied to.
"""

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


@pytest.fixture(autouse=True)
def _no_carrier_less_leftovers():
    """Start and end with the process-wide bucket empty.

    It is process-wide by design (see :mod:`pandid.deprecation`), so without
    this one test's carrier-less finding turns up in the next test's
    ``validate()``. Both ends, so a failure here cannot be inherited from
    somewhere else or handed on.
    """
    from pandid.deprecation import _forget_unattached

    _forget_unattached()
    yield
    _forget_unattached()


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


def test_no_carrier_reports_against_every_sheet():
    """The documented cost of the carrier-less home, asserted rather than hoped.

    A free function has no sheet, so the finding lands on whichever sheets the
    process goes on to validate. Over-reporting, deliberately, in preference to
    dropping it.
    """
    with pytest.warns(DeprecationWarning):
        RETIRED.warn()
    assert len([i for i in Flowsheet("a").validate() if i.code == CODE]) == 1
    assert len([i for i in Flowsheet("b").validate() if i.code == CODE]) == 1


def test_a_carrier_less_finding_says_it_once():
    with pytest.warns(DeprecationWarning):
        RETIRED.warn()
        RETIRED.warn()
    assert len([i for i in Flowsheet("a").validate() if i.code == CODE]) == 1


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
    assert declared, "the walker found nothing in a package that declares two"
    assert {where.rsplit(".", 1)[1] for where in declared} == {
        "_RETIRED_VAPOR_DRAW",
        "_RETIRED_LIQUID_DRAW",
    }
