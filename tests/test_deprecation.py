"""Test the deprecation mechanism: one declaration, a warning and a finding."""

import importlib
import pkgutil
import warnings

import pytest

import pandid
from pandid import Flowsheet, units as U
from pandid.deprecation import CODE, Deprecation

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


#: A stand-in deprecation for the tests to raise.
RETIRED = Deprecation(
    what="Pump(cooled=True)",
    instead="Pump(jacket='cooling')",
    removed_in="99.0.0",
)


def declarations() -> dict[str, Deprecation]:
    """Return every module-level :class:`Deprecation` in pandid."""
    found: dict[str, Deprecation] = {}
    for info in pkgutil.walk_packages(pandid.__path__, prefix="pandid."):
        module = importlib.import_module(info.name)
        for name, value in vars(module).items():
            if isinstance(value, Deprecation):
                found[f"{info.name}.{name}"] = value
    return found


class _OldPump(U.Pump):
    """A pump that warns ``RETIRED`` on construction."""

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


def test_the_warning_and_the_finding_are_the_same_sentence():
    """Check that the warning and the ``validate()`` finding carry the same message."""
    fs = Flowsheet("same")
    with pytest.warns(DeprecationWarning) as caught:
        fs.add(_OldPump("P-101"))
    warned = str(caught[0].message)
    reported = [i for i in fs.validate() if i.code == CODE]
    assert [warned] == [i.message for i in reported]


def test_the_warning_points_at_the_callers_line(same_file):
    """Check that the warning points at the caller's file."""
    with pytest.warns(DeprecationWarning) as caught:
        _OldPump("P-101")
    assert same_file(caught[0].filename) == same_file(__file__)


# --- carried from construction to validate() ---------------------------------


def test_a_unit_deprecated_before_add_is_still_reported():
    """Check that a unit deprecated before ``add`` is still reported by ``validate()``."""
    pump = _OldPump("P-101")
    assert pump.flowsheet is None
    fs = Flowsheet("late")
    fs.add(pump)
    assert [i.code for i in fs.validate()] == [CODE]


def test_a_unit_never_added_is_not_reported():
    _OldPump("P-101")
    fs = Flowsheet("empty")
    assert [i for i in fs.validate() if i.code == CODE] == []


# --- the carriers ------------------------------------------------------------


def test_one_carrier_says_it_once():
    """Check that a repeated warning on one carrier warns twice and reports once."""
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
    """Check that a flowsheet carries a deprecation of its own."""
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
    """Check that a deprecation with no carrier raises ``TypeError``."""
    for nothing in ((), (None,), (object(),)):
        with pytest.raises(TypeError, match="carrier"):
            RETIRED.warn(*nothing)


def test_a_refused_call_does_not_warn_either():
    """Check that a refused call raises without warning."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises(TypeError):
            RETIRED.warn(None)
    assert caught == []


def test_a_deprecation_stays_on_the_sheet_that_made_it():
    """Check that a deprecation reports on its own sheet and not on another."""
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
    """Check that two carriers with the same message both report."""
    fs = Flowsheet("twins")
    first = fs.add(U.Pump("P-101"))
    second = fs.add(U.Pump("P-102"))
    with pytest.warns(DeprecationWarning):
        RETIRED.warn(first)
        RETIRED.warn(second)
    assert len([i for i in fs.validate() if i.code == CODE]) == 2


def test_a_second_render_says_it_once_too():
    """Check that rendering a sheet twice reports its deprecation once."""
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
    """Check that a deprecation's message reads without a ``where``."""
    assert RETIRED.message() == (
        "Pump(cooled=True) is deprecated and is removed in pandid 99.0.0; "
        "use Pump(jacket='cooling')"
    )


def test_a_replacement_that_is_not_a_drop_in_says_so_before_it_is_named():
    """Check that a ``note`` comes before the replacement in the message."""
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


def test_no_deprecation_has_outlived_its_release():
    """Check that no declared deprecation names the current or an older release."""
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


def test_declarations_finds_a_module_constant(monkeypatch: pytest.MonkeyPatch):
    """Check that ``declarations()`` finds a constant in a pandid subpackage module."""
    import pandid.layout.faces as faces

    monkeypatch.setattr(faces, "RETIRED", RETIRED, raising=False)
    assert declarations()["pandid.layout.faces.RETIRED"] is RETIRED


def test_the_package_declares_only_the_announced_deprecations():
    """Check that the package declares only the deprecations announced for removal in 0.1.7."""
    from pandid.flowsheet import _CONTROLLER_AT
    from pandid.routing import _RECOVER_EXITS, _ROUTER
    from pandid.streams import _LINE_COMPONENTS
    from pandid.units import _AT_FACE, _DEFAULT_FACES, _PLACEMENT_HINTS

    assert declarations() == {
        "pandid.flowsheet._CONTROLLER_AT": _CONTROLLER_AT,
        "pandid.routing._RECOVER_EXITS": _RECOVER_EXITS,
        "pandid.routing._ROUTER": _ROUTER,
        "pandid.streams._LINE_COMPONENTS": _LINE_COMPONENTS,
        "pandid.units._AT_FACE": _AT_FACE,
        "pandid.units._DEFAULT_FACES": _DEFAULT_FACES,
        "pandid.units._PLACEMENT_HINTS": _PLACEMENT_HINTS,
    }
