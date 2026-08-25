"""No public entry point may accept an argument it then discards.

Every silent-discard defect found in the last fortnight has one shape: a
signature offers a word, the author types it, and nothing on the sheet is any
different. ``debug=True`` into the draw.io exporter, ``jump_direction``
misspelled and read as ``== "vertical"``, ``kind="material"`` overwritten on a
utility port, ``pin(port=...)`` resolving a nozzle and recording nothing. Each
was found by a different review and fixed on its own; #495 asks instead for the
rule, and for the test that finds the *next* one.

The rule, and what "honoured" means here
----------------------------------------

    An argument a public entry point accepts must be capable of changing what
    that entry point does.

Stated as a test rather than as a wish: hand the argument a value **no code in
this package could sensibly mean**, and the call must either raise, or produce
a different sheet. If it returns the same drawing, the same model and the same
findings as the call that never mentioned the argument at all, then the
argument had no consequence -- it was accepted and dropped. That is the whole
detection, and it is why the check is *behavioural* rather than a comparison of
two signatures: #492 already holds ``to_svg``'s keywords against the renderer's,
and that seam is exactly one seam. A keyword can be forwarded correctly and
still be read by nobody.

Two probe values, not one, because "no consequence" has two spellings. A
parameter whose default is falsy (``debug=False``) reacts to any truthy value,
and one whose default is truthy (``isolation=True``) reacts to none of them --
so the probes are an alien object and a *falsy* alien object, and an argument
counts as honoured when **either** of them makes a difference. Dropping the
falsy probe silently stops ``add_valve_station``'s three ``True`` flags from
being checked at all; ``tests`` below plants exactly that.

What this cannot see, said plainly
----------------------------------

It reads consequences, never intent. An argument read into the wrong field, or
honoured with the wrong sign, changes the sheet and passes here. So does one
whose only effect is a value this file's witness does not look at -- which is
why the witness is deliberately wide: what the call returned, the model it
left (``to_dict``), the sheet that model draws (``to_svg``) and the findings it
recorded (``warnings``).

Two holes in particular, both measured rather than assumed -- each was left in
the package on purpose and this file was watched not to notice:

1. **Validated at the door and dropped on the way through.** A probe that is
   *refused* proves the argument reached a validator, and nothing beyond it.
   Three mutations were left in the package on purpose and not one of them
   failed anything here: ``to_svg`` passing ``page_size=None`` to its renderer
   after ``_prepare_to_draw`` has checked the real one; ``_read_stream``
   calling ``_flag(data["tabulate"])`` and throwing the answer away; ``pandid
   draw`` passing ``border=None`` to ``render()`` after argparse has checked
   ``--border`` against its own ``choices``.

   What would close it is a second-tier probe taken from *the values the
   refusal offers* -- argparse hands them over in ``action.choices`` -- with
   two of them required to draw different sheets. That needs a fixture per
   configuration in which each of those values can show: a crossing on the
   sheet before ``--crossing-style`` means anything, a P&ID before
   ``--connections`` does. That is a fact about fixtures rather than a rule, so
   it is not here. What is here for the render chain is #492's guard in
   ``tests/test_stream_table_sheet.py``, holding each entry point's keywords
   against its backend's, and ``tests/test_show.py``, holding ``show()``'s
   signature to ``render()``'s.
2. **Refused, but not by name.** #495 asks that a refusal name the argument.
   Several here raise something legible only to a Python programmer --
   ``AttributeError: '_Alien' object has no attribute 'upper'`` for a bad
   ``page_size`` -- and that counts as honoured. Demanding the name would flag
   forty-odd parameters whose fault is a missing type check rather than a
   silent discard, which is a different issue from this one.

``**opts`` is out of reach by construction: a catch-all has no parameter name to
poison. What replaces it is the other half of #492's rule, checked here for
every entry point that has one --
:func:`test_an_entry_point_with_a_catch_all_refuses_an_unknown_keyword`.

Declaring that an argument cannot apply
---------------------------------------

Some arguments legitimately do nothing in some configurations, and that is not
a defect. Three shapes of it turn up:

* a **protocol default**. ``Unit.repeats()`` answers False for every argument,
  because no piece of equipment is a second drawing of another one; the
  parameter is there for :meth:`Instrument.repeats` and :meth:`Tee.repeats` to
  read, and both are exercised here.
* an argument whose **companion is absent**. ``add_valve_station(gap=...)``
  measures a run that is only laid out when ``x`` and ``y`` are both given.
* an argument with **nothing to act on**. ``check=`` refuses a sheet with
  errors; a sheet with none has nothing to refuse. (Rather than declare that
  five times over, the render fixture here carries one deliberate error and
  every render case passes ``check=False`` in its baseline -- see
  :func:`_faulty_sheet`.)

The example that prompted the question -- ``connections="flanged"`` on a stream
table sheet, accepted and marking nothing -- turns out **not** to need one, and
the reason is worth keeping: ``to_svg`` checks ``connections`` before it decides
whether there is a diagram to mark, so a nonsense value is refused on a table
sheet exactly as it is on a drawing. An argument that is validated wherever it
is accepted is one this file can leave alone whether or not it applies, which
is another way of saying that #492 got that call right.

There is **one** place to say so, :data:`INAPPLICABLE`, and saying so is not
free: a declaration is held to be *true*. If a declared-inert argument turns
out to have an effect, this file fails and the line must go. That is what keeps
the table from becoming somewhere to put a failure.

A declaration that cites an issue number is a **defect that has been filed and
not yet fixed**, not a design decision; the two live in one table because the
guard treats them identically, and are told apart by
:attr:`Inapplicable.issue`.

Guarding the guard
------------------

Three PRs in one night shipped a regression guard that passed with its own
machinery stubbed out, so every mechanism this file leans on is broken on
purpose at the bottom and shown to produce a failure:

* the **enumeration** takes the namespace it walks as an argument, so a stub
  namespace with a planted class proves it finds one, and an empty one proves
  it reports nothing rather than everything;
* the **engine** is run against a function that provably swallows its argument
  and against one that provably reads it, and must tell them apart;
* the **tables** are validated by functions that take the table, so a
  fabricated table with a stale key, a blank reason or a malformed issue
  number is shown to be reported;
* the **parametrisation** is asserted non-empty and to contain named pairs, so
  a signature reader that quietly returned nothing cannot make the whole file
  pass by having nothing to check.
"""

import argparse
import copy
import inspect
import io
import json
import os
import re
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Iterable, Mapping

import pytest

import pandid
from pandid import Annotation, Component, Flowsheet, Revision, TableBox, TitleBlock
from pandid import cli as CLI
from pandid import devices as D
from pandid import spec as SPEC
from pandid import units as U
from pandid.loops import ControlLoop, Loop
from pandid.render.drawio import DrawioRenderer
from pandid.render.svg import SvgRenderer
from pandid.streams import Stream

# --------------------------------------------------------------------------
# The probes
# --------------------------------------------------------------------------


class _Alien:
    """A value nothing in this package can mean.

    Not ``None``, not ``0`` and not ``""``: every one of those is a value some
    argument here legitimately takes, and a probe an argument accepts proves
    nothing when the answer comes out unchanged. This has no length, no
    ``__float__``, no ``__iter__``, equality only with itself, and a ``__repr__``
    that is the same string every run -- so any code that reads it at all
    reacts, and nothing that stores it makes the witness differ from itself.
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return "<alien>"


class _FalsyAlien(_Alien):
    """The same, for an argument whose default is already truthy.

    ``add_valve_station(isolation=True)`` cannot tell an alien from its
    default, because ``if isolation:`` is true either way. This one is false,
    so the branch goes the other way and the difference shows.
    """

    __slots__ = ()

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:
        return "<falsy alien>"


#: The two probes every Python-level case uses.
PROBES: tuple[Any, ...] = (_Alien(), _FalsyAlien())

#: A string no option, key or spelling in this package accepts. The shell has
#: only strings to offer, so the command-line cases probe with this instead.
NONSENSE = "__pandid_no_such_value__"

#: The keyword used to test a ``**kwargs`` catch-all. Not a name any signature
#: here has, and deliberately not a near-miss of one.
UNKNOWN_KEYWORD = "no_such_keyword_at_all"


# --------------------------------------------------------------------------
# A case: one entry point, called one way
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Case:
    """One entry point in one configuration, and how to call it.

    ``run(**overrides)`` performs the call with its baseline arguments, with
    *overrides* replacing named ones, and returns a **string describing
    everything the call could have changed**. Two runs of the same case with
    the same overrides must produce the same string; that is asserted, because
    a witness with a memory address or a clock in it would make every argument
    look honoured and this whole file vacuous.

    ``arguments`` is read from the entry point rather than written here -- from
    :func:`inspect.signature` for a Python callable, from the parser's own
    actions for the command line, from the reader's own key set for a spec --
    so an argument added tomorrow is checked tomorrow.
    """

    id: str
    arguments: tuple[str, ...]
    run: Callable[..., str]
    #: The function whose public-surface coverage this case discharges. None
    #: for the surfaces that are not Python callables (the CLI, the spec).
    entry: Any = None
    probes: tuple[Any, ...] = field(default=PROBES)


@dataclass(frozen=True)
class Inapplicable:
    """Why an argument can have no effect in one configuration.

    *issue* turns the entry from a statement about the design into a defect
    that has been filed: ``"#527"``. Both are held to the same test -- the
    argument really must be inert -- and the only difference is what the
    failure message says when it stops being true.
    """

    reason: str
    issue: str = ""


def _parameters(func: Any) -> tuple[str, ...]:
    """Every argument *func* names, catch-alls excluded.

    ``*args``/``**kwargs`` are left out because there is no name in them to
    poison, not because they are safe:
    :func:`test_an_entry_point_with_a_catch_all_refuses_an_unknown_keyword` is
    what covers those.
    """
    return tuple(
        name
        for name, p in inspect.signature(func).parameters.items()
        if name not in ("self", "cls") and p.kind not in (p.VAR_KEYWORD, p.VAR_POSITIONAL)
    )


def _has_catch_all(func: Any) -> bool:
    return any(p.kind is p.VAR_KEYWORD for p in inspect.signature(func).parameters.values())


# --------------------------------------------------------------------------
# The witnesses
# --------------------------------------------------------------------------


def _sheet_state(fs: Flowsheet, result: object = None) -> str:
    """Everything a call on *fs* could have left behind.

    Four readings, because a defect in this class hides in whichever one is
    left out: what the call handed back, the model it wrote, the drawing that
    model makes, and the findings it recorded. An exception from any of them is
    part of the reading rather than a failure -- a poisoned model that cannot
    be drawn is a model that changed.

    ``check=False``, so what is compared is the *drawing* rather than the
    validator's opinion of it; ``warnings`` carries the opinion separately.
    """
    parts = [repr(result)]
    for label, produce in (
        ("model", lambda: json.dumps(fs.to_dict(), sort_keys=True, default=repr)),
        ("sheet", lambda: fs.to_svg(check=False)),
    ):
        try:
            parts.append(f"{label}: {produce()}")
        except Exception as exc:
            # Caught rather than raised: a model that can no longer be written
            # out or drawn is a model that *changed*, so the exception is part
            # of the reading and not a failure of the reading.
            parts.append(f"{label} raised {type(exc).__name__}: {exc}")
    parts.append(f"warnings: {[str(w) for w in fs.warnings]}")
    return "\n".join(parts)


def _outcome(case: Case, **overrides: Any) -> str:
    """Run *case* and describe what happened, exception included.

    ``SystemExit`` by name, because that is how a refused command line reports
    itself; nothing wider than that, so a ``KeyboardInterrupt`` still stops the
    run rather than being read as a difference.
    """
    try:
        return "returned\n" + case.run(**overrides)
    except (Exception, SystemExit) as exc:
        return f"raised {type(exc).__name__}: {exc}"


def _honoured(case: Case, argument: str) -> bool:
    """Whether *argument* can change what *case* does.

    True as soon as one probe makes a difference. False means every probe left
    the call returning the same value, writing the same model, drawing the same
    sheet and recording the same findings as the baseline -- which is what
    "accepted and discarded" looks like from outside.
    """
    baseline = _outcome(case)
    return any(_outcome(case, **{argument: probe}) != baseline for probe in case.probes)


# --------------------------------------------------------------------------
# The fixtures the cases are built on
# --------------------------------------------------------------------------


def _sheet() -> Flowsheet:
    """A small, valid sheet with something of each kind on it.

    A feed, a vessel, a valve and a product, piped in a line, with a line
    number on the first run and a tabulated property on every one -- so that a
    keyword about line numbers, or about the stream table, has something to
    act on.
    """
    fs = Flowsheet("Argument Contract")
    feed = fs.add(U.Feed("F-1"))
    tank = fs.add(U.Vessel("T-1"))
    valve = fs.add(U.Valve("HV-1"))
    product = fs.add(U.Product("PR-1"))
    fs.connect(feed.outlet, tank.inlet, size=6, service="P", spec="A1A")
    fs.connect(tank.outlet, valve.inlet)
    fs.connect(valve.outlet, product.inlet)
    for stream in fs.streams:
        stream.properties["Mass Flow"] = "100"
    return fs


def _faulty_sheet() -> Flowsheet:
    """:func:`_sheet` with one deliberate error on it.

    ``check=`` is the argument that refuses a sheet whose validation failed. On
    a sheet that passes, ``check=True`` and ``check=False`` draw the same file
    and no probe can tell that the argument was read at all -- so every render
    case here is built on a sheet that *does* fail, with ``check=False`` in its
    baseline. The alien probe is truthy, turns the checking back on, and the
    call raises.

    Two units pinned on the same point is the error, because it is one the
    validator reports on every diagram type and with the table on or off. What
    it costs is a fixture whose two symbols overlap, which no assertion here
    looks at.
    """
    fs = _sheet()
    fs.units[1].pin(x=200, y=200)
    fs.units[2].pin(x=200, y=200)
    return fs


# --------------------------------------------------------------------------
# The cases: Python callables
# --------------------------------------------------------------------------

CASES: dict[str, Case] = {}


def _case(case: Case) -> Case:
    if case.id in CASES:
        raise AssertionError(f"two cases share the id {case.id!r}")
    CASES[case.id] = case
    return case


def _render_case(cid: str, method: str, **fixed: Any) -> Case:
    """One of the four output calls, in one configuration."""

    def run(**overrides: Any) -> str:
        kwargs: dict[str, Any] = {"check": False, **fixed, **overrides}
        fs = _faulty_sheet()
        if method == "render":
            with tempfile.TemporaryDirectory() as tmp:
                path = kwargs.pop("path", str(Path(tmp) / f"sheet{fixed['_suffix']}"))
                kwargs.pop("_suffix", None)
                fs.render(path, **kwargs)
                written = Path(str(path))
                body = written.read_text(encoding="utf-8") if written.exists() else "(none)"
            return body
        if method == "show":
            from pandid.render import preview as preview_module

            seen: dict[str, str] = {}
            original = preview_module.preview

            def fake(svg: str, *, title: str = "") -> None:
                seen["svg"], seen["title"] = svg, title

            preview_module.preview = fake  # type: ignore[assignment]
            try:
                fs.show(**kwargs)
            finally:
                preview_module.preview = original  # type: ignore[assignment]
            return seen.get("svg", "(nothing shown)") + "\n" + seen.get("title", "")
        kwargs.pop("_suffix", None)
        return str(getattr(fs, method)(**kwargs))

    entry = getattr(Flowsheet, method)
    return _case(Case(id=cid, arguments=_parameters(entry), run=run, entry=entry))


_render_case("to_svg[pfd]", "to_svg")
_render_case("to_svg[p&id]", "to_svg", diagram="p&id")
_render_case("to_svg[bfd]", "to_svg", diagram="bfd")
_render_case("to_svg[table docked]", "to_svg", show_stream_table=True, page_size="A3")
_render_case("to_svg[table sheet]", "to_svg", show_stream_table="sheet", page_size="A3")
_render_case("to_drawio[pfd]", "to_drawio")
_render_case("to_drawio[table sheet]", "to_drawio", show_stream_table="sheet", page_size="A3")
_render_case("render[.svg]", "render", _suffix=".svg")
_render_case("render[.drawio]", "render", _suffix=".drawio")
_render_case("show[]", "show")


def _backend_case(cid: str, backend: Any) -> Case:
    """A render backend called directly, which is what ``Renderer`` promises."""

    def run(**overrides: Any) -> str:
        fs = _faulty_sheet()
        fs.route()
        return str(backend().render(fs, **overrides))

    return _case(Case(id=cid, arguments=_parameters(backend.render), run=run, entry=backend.render))


_backend_case("SvgRenderer.render", SvgRenderer)
_backend_case("DrawioRenderer.render", DrawioRenderer)


def _sheet_case(cid: str, entry: Any, call: Callable[[Flowsheet, dict[str, Any]], object]) -> Case:
    """A call that changes the model: judged on the sheet it leaves behind."""

    def run(**overrides: Any) -> str:
        fs = _sheet()
        kwargs = dict(overrides)
        result = call(fs, kwargs)
        return _sheet_state(fs, result)

    return _case(Case(id=cid, arguments=_parameters(entry), run=run, entry=entry))


def _default(kwargs: dict[str, Any], **defaults: Any) -> dict[str, Any]:
    """*kwargs* with each default filled in where the probe did not override it."""
    for name, value in defaults.items():
        kwargs.setdefault(name, value)
    return kwargs


_sheet_case("Flowsheet.layout", Flowsheet.layout, lambda fs, kw: fs.layout(**kw))
_sheet_case("Flowsheet.route", Flowsheet.route, lambda fs, kw: fs.route(**kw))
_sheet_case(
    "Flowsheet.validate",
    Flowsheet.validate,
    lambda fs, kw: [str(i) for i in fs.validate(**kw)],
)
_sheet_case(
    "Flowsheet.add",
    Flowsheet.add,
    lambda fs, kw: fs.add(**_default(kw, unit=U.Vessel("V-9"))).name,
)
_sheet_case(
    "Flowsheet.add_component",
    Flowsheet.add_component,
    lambda fs, kw: fs.add_component(**_default(kw, component=Component("Water", "H2O"))),
)
_sheet_case(
    "Flowsheet.add_annotation",
    Flowsheet.add_annotation,
    lambda fs, kw: fs.add_annotation(
        **_default(kw, annotation=Annotation(title="Notes", rows=["one"]))
    ),
)
_sheet_case(
    "Flowsheet.add_loop",
    Flowsheet.add_loop,
    lambda fs, kw: fs.add_loop(**_default(kw, variable="T")).name,
)
_sheet_case(
    "Flowsheet.add_instrument",
    Flowsheet.add_instrument,
    lambda fs, kw: fs.add_instrument(**_default(kw, type="TI", number=101, near=fs.units[1])).name,
)
_sheet_case(
    "Flowsheet.add_balloon",
    Flowsheet.add_balloon,
    lambda fs, kw: fs.add_balloon(**_default(kw, element=fs.units[1])).name,
)
_sheet_case(
    "Flowsheet.add_control_loop",
    Flowsheet.add_control_loop,
    lambda fs, kw: (
        fs.add_control_loop(
            **_default(kw, variable="L", measuring=fs.units[1], acting_on=fs.units[2])
        ).name
    ),
)
_sheet_case(
    "Flowsheet.connect",
    Flowsheet.connect,
    lambda fs, kw: (
        fs.connect(**_default(kw, src=fs.units[1].vent, dst=fs.add(U.Product("PR-2")).inlet)).name
    ),
)
_sheet_case(
    "Flowsheet.add_valve_station[placed]",
    Flowsheet.add_valve_station,
    lambda fs, kw: [
        u.name for u in fs.add_valve_station(**_default(kw, tag="CV-1", x=600.0, y=300.0)).members
    ],
)
_sheet_case(
    "Flowsheet.add_valve_station[unplaced]",
    Flowsheet.add_valve_station,
    lambda fs, kw: [u.name for u in fs.add_valve_station(**_default(kw, tag="CV-1")).members],
)


def _flowsheet_init(**overrides: Any) -> str:
    """A sheet built from the constructor's own arguments.

    Rich enough that every one of them has something to act on: a numbered
    stream, a line number, a loop, and a valve station whose members are tagged
    by ``valve_station_tag_scheme``.
    """
    fs = Flowsheet(**_default(dict(overrides), name="Argument Contract"))
    feed = fs.add(U.Feed("F-1"))
    tank = fs.add(U.Vessel("T-1"))
    fs.connect(feed.outlet, tank.inlet, size=6, service="P", spec="A1A")
    fs.add_loop("T")
    fs.add_valve_station("CV-1", x=600, y=300)
    return _sheet_state(fs)


_case(
    Case(
        id="Flowsheet.__init__",
        arguments=_parameters(Flowsheet.__init__),
        run=_flowsheet_init,
        entry=Flowsheet.__init__,
    )
)


# --- reading a spec back ------------------------------------------------------

BASE_SPEC: Mapping[str, Any] = {
    "name": "Argument Contract",
    "units": [
        {"name": "F-1", "kind": "feed"},
        {"name": "T-1", "kind": "vessel"},
        {"name": "HV-1", "kind": "valve"},
        {"name": "PR-1", "kind": "product"},
    ],
    "loops": [{"variable": "T", "number": 101}],
    "components": [{"name": "Water", "formula": "H2O"}],
    "instruments": [
        {"type": "TI", "number": 101, "near": "T-1"},
        {"balloon_of": "HV-1"},
    ],
    "streams": [
        {"from": ["F-1", "outlet"], "to": ["T-1", "inlet"], "properties": {"Mass Flow": "100"}},
        {"from": ["T-1", "outlet"], "to": ["HV-1", "inlet"]},
        {"from": ["HV-1", "outlet"], "to": ["PR-1", "inlet"]},
    ],
}


def _spec_file(tmp: str, name: str, text: str) -> str:
    path = Path(tmp) / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def _read_case(cid: str, entry: Any, reader: Callable[[dict[str, Any]], Flowsheet]) -> Case:
    def run(**overrides: Any) -> str:
        return _sheet_state(reader(dict(overrides)))

    return _case(Case(id=cid, arguments=_parameters(entry), run=run, entry=entry))


_read_case(
    "spec.from_dict",
    SPEC.from_dict,
    lambda kw: SPEC.from_dict(**_default(kw, spec=copy.deepcopy(dict(BASE_SPEC)))),
)
_read_case(
    "Flowsheet.from_dict",
    Flowsheet.from_dict,
    lambda kw: Flowsheet.from_dict(**_default(kw, spec=copy.deepcopy(dict(BASE_SPEC)))),
)


def _from_file(
    reader: Callable[..., Flowsheet], suffix: str, text: str
) -> Callable[..., Flowsheet]:
    def call(kw: dict[str, Any]) -> Flowsheet:
        with tempfile.TemporaryDirectory() as tmp:
            return reader(**_default(kw, path=_spec_file(tmp, f"spec{suffix}", text)))

    return call


_JSON_SPEC = json.dumps(BASE_SPEC)
_YAML_SPEC = json.dumps(BASE_SPEC)  # JSON is a subset of YAML, so this reads as either

_read_case("spec.from_json", SPEC.from_json, _from_file(SPEC.from_json, ".json", _JSON_SPEC))
_read_case(
    "Flowsheet.from_json",
    Flowsheet.from_json,
    _from_file(Flowsheet.from_json, ".json", _JSON_SPEC),
)
_read_case("spec.from_yaml", SPEC.from_yaml, _from_file(SPEC.from_yaml, ".yaml", _YAML_SPEC))
_read_case(
    "Flowsheet.from_yaml",
    Flowsheet.from_yaml,
    _from_file(Flowsheet.from_yaml, ".yaml", _YAML_SPEC),
)


def _spec_to_dict(**overrides: Any) -> str:
    kwargs = _default(dict(overrides), fs=_sheet())
    return json.dumps(SPEC.to_dict(**kwargs), sort_keys=True, default=repr)


_case(
    Case(
        id="spec.to_dict",
        arguments=_parameters(SPEC.to_dict),
        run=_spec_to_dict,
        entry=SPEC.to_dict,
    )
)


# --- the records an author builds and hands to the sheet ----------------------


def _record_case(
    cid: str, entry: Any, install: Callable[[Flowsheet, dict[str, Any]], None]
) -> Case:
    def run(**overrides: Any) -> str:
        fs = _sheet()
        install(fs, dict(overrides))
        return _sheet_state(fs)

    return _case(Case(id=cid, arguments=_parameters(entry), run=run, entry=entry))


def _install_title_block(fs: Flowsheet, kw: dict[str, Any]) -> None:
    fs.title_block = TitleBlock(**_default(kw, title="Argument Contract"))


def _install_revision(fs: Flowsheet, kw: dict[str, Any]) -> None:
    fs.title_block = TitleBlock(title="T", revisions=[Revision(**_default(kw, rev="A"))])


def _install_annotation(fs: Flowsheet, kw: dict[str, Any]) -> None:
    fs.add_annotation(Annotation(**_default(kw, title="Notes", rows=["one", "two"])))


def _install_table_box(fs: Flowsheet, kw: dict[str, Any]) -> None:
    fs.add_annotation(
        TableBox(**_default(kw, title="Legend", headers=["a", "b"], rows=[["1", "2"]]))
    )


def _install_component(fs: Flowsheet, kw: dict[str, Any]) -> None:
    fs.add_component(Component(**_default(kw, name="Water")))


_record_case("TitleBlock()", TitleBlock.__init__, _install_title_block)
_record_case("Revision()", Revision.__init__, _install_revision)
_record_case("Annotation()", Annotation.__init__, _install_annotation)
_record_case("TableBox()", TableBox.__init__, _install_table_box)
_record_case("Component()", Component.__init__, _install_component)


# --- every distinct unit constructor -----------------------------------------


def _unit_classes() -> dict[Any, type]:
    """Each distinct ``__init__`` among the public unit and device classes.

    Keyed by the function, so ``Blower``, ``Pump`` and fifty-four others that
    share :meth:`Unit.__init__` are one case rather than fifty-six, and a class
    that grows a constructor of its own becomes a case of its own the day it
    does.
    """
    found: dict[Any, type] = {}
    for name in sorted(set(U.__all__) | set(D.__all__)):
        cls = getattr(pandid, name)
        if not (isinstance(cls, type) and issubclass(cls, U.Unit)):
            continue
        found.setdefault(cls.__init__, cls)
    return found


def _unit_constructor_case(cls: type) -> Case:
    def run(**overrides: Any) -> str:
        fs = _sheet()
        kwargs = dict(overrides)
        if issubclass(cls, U.Instrument):
            _default(kwargs, type="TI", number=901)
        else:
            _default(kwargs, name="X-901")
        unit = fs.add(cls(**kwargs))
        return _sheet_state(fs, unit.name)

    return _case(
        Case(
            id=f"{cls.__name__}()",
            arguments=_parameters(cls.__init__),
            run=run,
            entry=cls.__init__,
        )
    )


for _init, _cls in _unit_classes().items():
    _unit_constructor_case(_cls)


# --- the methods on a unit ----------------------------------------------------


def _unit_case(cid: str, entry: Any, call: Callable[[Flowsheet, dict[str, Any]], object]) -> Case:
    return _sheet_case(cid, entry, call)


def _multiport(fs: Flowsheet, cls: type) -> Any:
    """A unit whose connection faces can be counted, named and reordered."""
    return fs.add(cls("MP-901", inputs=2, outputs=2))


for _cls, _tag in ((U.Block, "Block"), (U.Vessel, "Vessel")):
    _unit_case(
        f"{_tag}.face",
        _cls.face,
        (lambda cls: lambda fs, kw: _multiport(fs, cls).face(**_default(kw, port_name="in_1")))(
            _cls
        ),
    )
    _unit_case(
        f"{_tag}.ports_on",
        _cls.ports_on,
        (
            lambda cls: (
                lambda fs, kw: [
                    p.name for p in _multiport(fs, cls).ports_on(**_default(kw, face="W"))
                ]
            )
        )(_cls),
    )
    _unit_case(
        f"{_tag}.order_on",
        _cls.order_on,
        (lambda cls: lambda fs, kw: _order_on(_multiport(fs, cls), kw))(_cls),
    )
    _unit_case(
        f"{_tag}.nozzle",
        _cls.nozzle,
        (
            lambda cls: (
                lambda fs, kw: (
                    _multiport(fs, cls).nozzle(**_default(kw, port_name="in_1", face="W")).name
                )
            )
        )(_cls),
    )
    _unit_case(
        f"{_tag}.pin",
        _cls.pin,
        (lambda cls: lambda fs, kw: _multiport(fs, cls).pin(**kw).name)(_cls),
    )


def _order_on(unit: Any, kw: dict[str, Any]) -> object:
    _default(kw, face="W", ports=tuple(unit.ports_on("W"))[::-1])
    return [p.name for p in unit.order_on(**kw).ports_on("W")]


_unit_case(
    "Unit.port",
    U.Unit.port,
    lambda fs, kw: fs.units[1].port(**_default(kw, name="inlet")).name,
)
_unit_case(
    "Unit.repeats",
    U.Unit.repeats,
    lambda fs, kw: fs.units[1].repeats(**_default(kw, other=fs.units[2])),
)
_unit_case(
    "Unit.has_another_port",
    U.Unit.has_another_port,
    lambda fs, kw: fs.units[1].has_another_port(**_default(kw, port=fs.units[1].port("inlet"))),
)
_unit_case(
    "Unit.another_port",
    U.Unit.another_port,
    lambda fs, kw: fs.units[1].another_port(**_default(kw, port=fs.units[1].port("inlet"))).name,
)
# On the valve rather than on the vessel: Vessel inherits ``nozzle`` from
# ``_MultiPortVessel``, so a case built on one would exercise the override and
# leave Unit.nozzle -- the one every other symbol uses -- untouched. Which
# function a case really reaches is asserted, not assumed; see
# :func:`test_a_case_runs_the_entry_point_it_says_it_covers`.
_unit_case(
    "Unit.nozzle",
    U.Unit.nozzle,
    lambda fs, kw: fs.units[2].nozzle(**_default(kw, port_name="inlet", face="W")).name,
)
_unit_case(
    "Unit.pin",
    U.Unit.pin,
    lambda fs, kw: fs.units[1].pin(**kw).name,
)
_unit_case(
    "Unit.pin[on an attached balloon]",
    U.Unit.pin,
    lambda fs, kw: _pin_a_balloon(fs, kw),
)


def _pin_a_balloon(fs: Flowsheet, kw: dict[str, Any]) -> object:
    inst = fs.add_instrument("PI", 101, near=fs.units[1])
    inst.attach(fs.streams[0])
    return inst.pin(**kw).name


def _composition_case(cid: str, cls: type) -> Case:
    def run(**overrides: Any) -> str:
        kwargs = _default(dict(overrides), variant="default")
        return repr(sorted(cls.composition_defaults(**kwargs).items(), key=repr))

    return _case(
        Case(
            id=cid,
            arguments=_parameters(cls.composition_defaults),
            run=run,
            entry=cls.composition_defaults.__func__,
        )
    )


_composition_case("Unit.composition_defaults", U.Vessel)
_composition_case("Reactor.composition_defaults", U.Reactor)


def _repeats_case(cid: str, entry: Any, build: Callable[[], tuple[Any, Any]]) -> Case:
    def run(**overrides: Any) -> str:
        first, second = build()
        return repr(first.repeats(**_default(dict(overrides), other=second)))

    return _case(Case(id=cid, arguments=_parameters(entry), run=run, entry=entry))


# A trip square, because that is the symbol a tag may legitimately carry twice:
# a plain indicator answers False to every argument and would prove nothing.
_repeats_case(
    "Instrument.repeats",
    U.Instrument.repeats,
    lambda: (U.Instrument("XS", 101, variant="logic"), U.Instrument("XS", 101, variant="logic")),
)
_repeats_case(
    "Tee.repeats",
    U.Tee.repeats,
    lambda: (U.Tee(), U.Tee()),
)
_repeats_case(
    "Feed.repeats",
    U.Feed.repeats,
    lambda: (U.Feed("CWS", header=True), U.Feed("CWS", header=True)),
)


def _pool_case(
    cid: str,
    entry: Any,
    call: Callable[[Any, dict[str, Any]], object],
    build: Callable[[Flowsheet], Any],
) -> Case:
    def run(**overrides: Any) -> str:
        fs = _sheet()
        return _sheet_state(fs, call(build(fs), dict(overrides)))

    return _case(Case(id=cid, arguments=_parameters(entry), run=run, entry=entry))


def _an_instrument(fs: Flowsheet) -> Any:
    return fs.add_instrument("PI", 101, near=fs.units[1])


def _a_header(fs: Flowsheet) -> Any:
    return fs.add(U.Feed("CWS", header=True))


_pool_case(
    "Instrument.has_another_port",
    U.Instrument.has_another_port,
    lambda inst, kw: inst.has_another_port(**_default(kw, port=inst.signal_port("sig_out"))),
    _an_instrument,
)
_pool_case(
    "Instrument.another_port",
    U.Instrument.another_port,
    lambda inst, kw: inst.another_port(**_default(kw, port=inst.signal_port("sig_out"))).name,
    _an_instrument,
)
_pool_case(
    "Feed.has_another_port",
    U.Feed.has_another_port,
    lambda unit, kw: unit.has_another_port(**_default(kw, port=unit.port("outlet"))),
    _a_header,
)
_pool_case(
    "Feed.another_port",
    U.Feed.another_port,
    lambda unit, kw: unit.another_port(**_default(kw, port=unit.port("outlet"))).name,
    _a_header,
)
_pool_case(
    "Instrument.attach",
    U.Instrument.attach,
    lambda inst, kw: inst.attach(**_default(kw, on=inst.flowsheet.streams[0])).name,
    _an_instrument,
)
_pool_case(
    "Instrument.annotate",
    U.Instrument.annotate,
    lambda inst, kw: inst.annotate(**kw).name,
    _an_instrument,
)
_pool_case(
    "Instrument.signal_port",
    U.Instrument.signal_port,
    lambda inst, kw: inst.signal_port(**_default(kw, name="sig_out")).name,
    _an_instrument,
)


def _stream_via(**overrides: Any) -> str:
    fs = _sheet()
    result = fs.streams[0].via(**_default(dict(overrides), waypoints=[(400.0, 400.0)]))
    return _sheet_state(fs, result.name)


_case(
    Case(
        id="Stream.via",
        arguments=_parameters(Stream.via),
        run=_stream_via,
        entry=Stream.via,
    )
)


# --- the loop handles ---------------------------------------------------------


def _loop_case(cid: str, entry: Any, build: Callable[[Flowsheet], Any], method: str) -> Case:
    def run(**overrides: Any) -> str:
        fs = _sheet()
        handle = build(fs)
        return _sheet_state(fs, getattr(handle, method)(**_default(dict(overrides), letters="TI")))

    return _case(Case(id=cid, arguments=_parameters(entry), run=run, entry=entry))


def _a_loop(fs: Flowsheet) -> Loop:
    return fs.add_loop("T")


def _a_control_loop(fs: Flowsheet) -> ControlLoop:
    return fs.add_control_loop("T", measuring=fs.units[1], acting_on=fs.units[2])


for _method in ("tag", "element", "check"):
    _loop_case(f"Loop.{_method}", getattr(Loop, _method), _a_loop, _method)
    _loop_case(f"ControlLoop.{_method}", getattr(ControlLoop, _method), _a_control_loop, _method)


# --- the properties that can be set -------------------------------------------


def _settable_properties(namespace: Mapping[str, object]) -> dict[str, tuple[type, str]]:
    """Every public property in *namespace* that has a setter.

    A setter is an entry point with exactly one argument, and an argument
    written into an attribute nobody reads is the same defect as one dropped on
    the floor.
    """
    found: dict[str, tuple[type, str]] = {}
    seen: set[Any] = set()
    for name in sorted(namespace):
        obj = namespace[name]
        if not inspect.isclass(obj):
            continue
        for attr in sorted(vars(obj)):
            prop = vars(obj)[attr]
            if attr.startswith("_") or not isinstance(prop, property) or prop.fset is None:
                continue
            if prop.fset in seen:
                continue
            seen.add(prop.fset)
            found[f"{obj.__name__}.{attr} ="] = (obj, attr)
    return found


#: What each settable property is exercised on. Anything not named here is a
#: fresh unit of the owning class, added to the sheet and left standing alone;
#: the entries are the classes for which that is not enough to see the setting.
#: ``Unit`` is the sharp one -- ``new_line_number`` breaks a line number across
#: a fitting, so the host has to be a fitting with a line running through it.
_PROPERTY_HOSTS: dict[str, Callable[[Flowsheet], Any]] = {
    "Flowsheet": lambda fs: fs,
    "Unit": lambda fs: fs.units[2],
    "Valve": lambda fs: fs.units[2],
    "Block": lambda fs: fs.add(U.Block("B-901", inputs=2, outputs=2)),
    "Tee": lambda fs: fs.add(U.Tee()),
}


def _property_case(cid: str, owner: type, attr: str) -> Case:
    def run(**overrides: Any) -> str:
        fs = _sheet()
        host = _PROPERTY_HOSTS.get(owner.__name__)
        target = host(fs) if host is not None else fs.add(owner("X-901"))
        if attr in overrides:
            setattr(target, attr, overrides[attr])
        return _sheet_state(fs)

    return _case(Case(id=cid, arguments=(attr,), run=run))


def _property_namespace() -> dict[str, object]:
    return {"Flowsheet": Flowsheet, **{n: getattr(pandid, n) for n in pandid.__all__}}


#: No filter on which classes are taken. A settable property on a class this
#: file cannot instantiate would fail
#: :func:`test_a_case_makes_its_baseline_call_without_raising` loudly, which is
#: the right way to find out; skipping the ones that do not fit is how a
#: surface quietly stops being covered.
for _cid, (_owner, _attr) in _settable_properties(_property_namespace()).items():
    _property_case(_cid, _owner, _attr)


# --------------------------------------------------------------------------
# The cases: the spec reader's keys
# --------------------------------------------------------------------------


def _spec_outcome(spec: Mapping[str, Any]) -> str:
    fs = SPEC.from_dict(spec)
    return (
        json.dumps(SPEC.to_dict(fs), sort_keys=True, default=repr) + "\n" + fs.to_svg(check=False)
    )


def _spec_case(
    cid: str,
    keys: Iterable[str],
    baseline: Mapping[str, Any],
    place: Callable[[dict[str, Any], str, Any], None],
) -> Case:
    """One section of the spec format, probed key by key.

    The baseline is the section *without* the key, exactly as a Python
    parameter's baseline is its default; the probe is the section with the key
    set to a value nothing accepts. A key the reader lists as allowed and then
    never reads leaves the two identical.
    """

    def run(**overrides: Any) -> str:
        spec = copy.deepcopy(dict(baseline))
        for key, value in overrides.items():
            place(spec, key, value)
        return _spec_outcome(spec)

    return _case(Case(id=cid, arguments=tuple(sorted(keys)), run=run, probes=(*PROBES, NONSENSE)))


def _spec_base(**extra: Any) -> dict[str, Any]:
    spec = copy.deepcopy(dict(BASE_SPEC))
    spec.update(extra)
    return spec


_spec_case("spec:top", SPEC._TOP_KEYS, _spec_base(), lambda s, k, v: s.__setitem__(k, v))
_spec_case(
    "spec:unit", SPEC._UNIT_KEYS, _spec_base(), lambda s, k, v: s["units"][1].__setitem__(k, v)
)
_spec_case(
    "spec:pin",
    SPEC._PIN_KEYS,
    _spec_base(),
    lambda s, k, v: s["units"][1].setdefault("pin", {}).__setitem__(k, v),
)
_spec_case(
    "spec:stream",
    SPEC._STREAM_KEYS,
    _spec_base(),
    lambda s, k, v: s["streams"][0].__setitem__(k, v),
)
_spec_case(
    "spec:instrument",
    SPEC._INSTRUMENT_KEYS,
    _spec_base(),
    lambda s, k, v: s["instruments"][0].__setitem__(k, v),
)
_spec_case(
    "spec:balloon",
    SPEC._BALLOON_KEYS,
    _spec_base(),
    lambda s, k, v: s["instruments"][1].__setitem__(k, v),
)
_spec_case(
    "spec:quadrants",
    SPEC._QUADRANT_KEYS,
    _spec_base(),
    lambda s, k, v: s["instruments"][0].setdefault("quadrants", {}).__setitem__(k, v),
)
_spec_case(
    "spec:loop", SPEC._LOOP_KEYS, _spec_base(), lambda s, k, v: s["loops"][0].__setitem__(k, v)
)
_spec_case(
    "spec:component",
    SPEC._COMPONENT_KEYS,
    _spec_base(),
    lambda s, k, v: s["components"][0].__setitem__(k, v),
)

#: A minimal, valid entry of each annotation type, so the keys that type
#: accepts have a box to act on.
_ANNOTATION_BASES: dict[str, dict[str, Any]] = {
    "annotation": {"type": "annotation", "title": "Notes", "rows": ["one", "two"]},
    "table": {"type": "table", "title": "T", "headers": ["a", "b"], "rows": [["1", "2"]]},
    "equipment_list": {"type": "equipment_list", "title": "Equipment"},
    "notes": {"type": "notes", "title": "N", "items": ["one", "two"]},
    "legend": {"type": "legend", "title": "L", "entries": {"HP": "High Pressure"}},
}

for _kind, _keys in sorted(SPEC._ANNOTATION_KEYS.items()):
    _spec_case(
        f"spec:annotation[{_kind}]",
        _keys,
        _spec_base(annotations=[dict(_ANNOTATION_BASES[_kind])]),
        lambda s, k, v: s["annotations"][0].__setitem__(k, v),
    )


def _kind_key_owners() -> dict[str, tuple[str, ...]]:
    """The per-kind spec keys, grouped by the class each is exercised on.

    :data:`pandid.spec._KIND_KEYS` maps a key to every class that may carry it;
    the first is enough to prove the key is read, and grouping keeps the number
    of specs built down to one per class.
    """
    grouped: dict[str, list[str]] = {}
    for key, owners in SPEC._KIND_KEYS.items():
        grouped.setdefault(owners[0], []).append(key)
    return {owner: tuple(sorted(keys)) for owner, keys in sorted(grouped.items())}


#: Keys that need company before they mean anything: an order along a face
#: needs ports to order, a feed stage needs a feed.
_KIND_COMPANIONS: dict[str, dict[str, Any]] = {
    "Block": {"inputs": 2, "outputs": 2},
    "Column": {"n_feeds": 2, "n_draws": 2},
}

for _owner_name, _owner_keys in _kind_key_owners().items():
    _entry = {"name": f"{_owner_name}-901", "kind": _owner_name}
    _entry.update(_KIND_COMPANIONS.get(_owner_name, {}))
    _spec_case(
        f"spec:kind[{_owner_name}]",
        _owner_keys,
        _spec_base(units=[*BASE_SPEC["units"], _entry]),
        lambda s, k, v: s["units"][-1].__setitem__(k, v),
    )


# --------------------------------------------------------------------------
# The cases: the command line
# --------------------------------------------------------------------------

#: How each subcommand is invoked with nothing unusual asked of it.
_CLI_BASELINES: dict[str, list[str]] = {
    "draw": ["draw", "@SPEC@", "-o", "@OUT@"],
    "validate": ["validate", "@SPEC@"],
    "symbols": ["symbols"],
}


def _cli_actions(sub: argparse.ArgumentParser) -> dict[str, argparse.Action]:
    """Every option and positional the subcommand declares, by its dest.

    Read off the parser rather than listed here, so an option added to the
    shell is probed the day it is added -- which is the same rule the Python
    cases follow, through a different door.
    """
    return {
        action.dest: action
        for action in sub._actions
        if action.dest not in ("help", argparse.SUPPRESS)
    }


def _cli_case(name: str, sub: argparse.ArgumentParser) -> Case:
    actions = _cli_actions(sub)

    def run(**overrides: Any) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            spec_path = _spec_file(tmp, "spec.json", _JSON_SPEC)
            out_path = str(Path(tmp) / "out.svg")
            argv: list[str] = []
            for token in _CLI_BASELINES[name]:
                argv.append(
                    spec_path if token == "@SPEC@" else out_path if token == "@OUT@" else token
                )
            for dest, value in overrides.items():
                action = actions[dest]
                if action.option_strings:
                    argv.append(action.option_strings[-1])
                    if action.nargs != 0:
                        argv.append(str(value))
                else:
                    argv = [str(value) if a == spec_path else a for a in argv]
            out, err = io.StringIO(), io.StringIO()
            # Inside the temporary directory, because a relative --output is
            # written where the shell is standing: probing it with a bare name
            # left a file in the checkout on the first run of this file.
            here = os.getcwd()
            os.chdir(tmp)
            try:
                with redirect_stdout(out), redirect_stderr(err):
                    code: object = CLI.main(argv)
            except SystemExit as exc:
                code = f"SystemExit {exc.code}"
            finally:
                os.chdir(here)
            body = ""
            for path in sorted(Path(tmp).iterdir()):
                if path.is_file():
                    body += path.name + "\n" + path.read_text(encoding="utf-8", errors="replace")
            # The temporary directory's name is different every run and is
            # printed back by `pandid draw`; scrubbed, or every case would look
            # non-deterministic and every argument would look honoured.
            text = f"{code}\n{out.getvalue()}\n{err.getvalue()}\n{body}"
            return text.replace(tmp, "<tmp>").replace(str(Path(tmp)), "<tmp>")

    return _case(
        Case(id=f"cli:{name}", arguments=tuple(sorted(actions)), run=run, probes=(NONSENSE,))
    )


def _cli_subcommands() -> dict[str, argparse.ArgumentParser]:
    parser = CLI._build_parser()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    raise AssertionError("the CLI parser grew no subcommands")


for _name, _sub in sorted(_cli_subcommands().items()):
    _cli_case(_name, _sub)


# --------------------------------------------------------------------------
# The one place an argument is declared inert
# --------------------------------------------------------------------------

INAPPLICABLE: dict[tuple[str, str], Inapplicable] = {
    # --- protocol defaults: the parameter is read by the overrides -----------
    ("Unit.repeats", "other"): Inapplicable(
        "no piece of equipment is a second drawing of another one, so the base "
        "answers False whoever it is asked about. Instrument.repeats, Tee.repeats "
        "and Feed.repeats are the overrides that read it, and all three are cases here."
    ),
    ("Unit.has_another_port", "port"): Inapplicable(
        "a pump has one suction: no nozzle on a piece of equipment has a second like "
        "it, so the base answers False for every port. Instrument.has_another_port and "
        "Feed.has_another_port are the overrides that read it, and both are cases here."
    ),
    ("Unit.composition_defaults", "variant"): Inapplicable(
        "a class whose defaults are the same whichever body is drawn returns its "
        "COMPOSITION as it stands. Reactor.composition_defaults is the override that "
        "reads the variant, and it is a case here."
    ),
    ("Unit.composition_defaults", "stated"): Inapplicable(
        "same: one part rules another out only where a class says so, and this base "
        "says nothing. Reactor.composition_defaults reads it."
    ),
    # --- filed defects, not design ------------------------------------------
    ("Flowsheet.add_valve_station[unplaced]", "mirrored"): Inapplicable(
        "read only inside `if x is not None and y is not None`, so a station with no "
        "x/y accepts mirrored= and pipes the run the way it always did",
        issue="#527",
    ),
    ("Flowsheet.add_valve_station[unplaced]", "gap"): Inapplicable(
        "edge-to-edge along a run that is only laid out when x and y are given",
        issue="#527",
    ),
    ("Flowsheet.add_valve_station[unplaced]", "bypass_rise"): Inapplicable(
        "the bypass leg is only pinned when x and y are given",
        issue="#527",
    ),
    ("Flowsheet.add_valve_station[unplaced]", "drain_drop"): Inapplicable(
        "the drain leg is only pinned when x and y are given",
        issue="#527",
    ),
}


#: Entry points the public surface has that no case here calls, and why. A name
#: is here because calling it cannot show what this file measures -- not
#: because it was inconvenient.
UNEXERCISED: dict[str, str] = {
    "pandid.ports.Port.__init__": (
        "a port is minted by the unit that declares it (Unit.PORTS) or by a pool "
        "(_next_member); an author reaches one through unit.port(name), which is a case here"
    ),
    "pandid.streams.Stream.__init__": (
        "connect() is the constructor an author calls, and it is a case here; the "
        "class itself is what connect() hands back"
    ),
    "pandid.geometry.Pin.__init__": (
        "Unit.pin() is how a pin is made, and it is a case here; Pin is the record it writes"
    ),
    "pandid.geometry.Frame.__init__": (
        "a frame is the layout engine's output, not an author's input"
    ),
    "pandid.geometry.Route.__init__": (
        "a route is the router's output; Stream.via() is the author's door to it and is a case"
    ),
    "pandid.validate.Issue.__init__": (
        "an issue is what validate() hands back, never something an author builds"
    ),
    "pandid.loops.Loop.__init__": (
        "fs.add_loop() mints a loop and registers it with the sheet; a Loop built "
        "directly belongs to no flowsheet and draws nothing"
    ),
    "pandid.loops.ControlLoop.__init__": (
        "fs.add_control_loop() builds one out of the instruments it also creates; "
        "the constructor takes those finished objects"
    ),
    "pandid.stations.ValveStation.__init__": (
        "fs.add_valve_station() builds one out of the units it also adds; the "
        "constructor takes those finished units and is a handle, not a unit"
    ),
}


# --------------------------------------------------------------------------
# The public surface
# --------------------------------------------------------------------------


def public_callables(namespaces: Mapping[str, Mapping[str, object]]) -> dict[Any, list[str]]:
    """Every public callable in *namespaces* that takes an argument.

    Classes are walked through their whole MRO rather than through
    ``vars(cls)``, because an override two classes up is a different entry
    point with a different contract: ``Feed.repeats`` is ``_Boundary.repeats``
    and answers differently from ``Unit.repeats``, and reading only the class's
    own dictionary would have missed it.

    Keyed by the function, so fifty-six unit classes sharing one ``__init__``
    are one entry point, and valued with every name it answers to.

    Taking the namespaces as an argument is what makes this testable: the
    fixtures at the bottom drive it with a stub namespace and check what comes
    back, which is not possible for a function that reaches for ``pandid``
    itself.
    """
    found: dict[Any, list[str]] = {}
    for space, members in namespaces.items():
        for name in sorted(members):
            if name.startswith("_"):
                continue
            obj = members[name]
            candidates: list[tuple[str, Any]] = []
            if inspect.isclass(obj):
                for attr in sorted(dir(obj)):
                    if attr.startswith("_") and attr != "__init__":
                        continue
                    raw = inspect.getattr_static(obj, attr, None)
                    func = getattr(raw, "__func__", raw)
                    if inspect.isfunction(func):
                        candidates.append((f"{obj.__name__}.{attr}", func))
            elif inspect.isfunction(obj):
                candidates.append((f"{space}.{name}", obj))
            for label, func in candidates:
                if not getattr(func, "__module__", "").startswith("pandid"):
                    continue
                if not _parameters(func):
                    continue
                found.setdefault(func, []).append(label)
    return found


def unrecognised_callables(namespaces: Mapping[str, Mapping[str, object]]) -> list[str]:
    """Public things that are callable and are not a plain function or a class.

    :func:`public_callables` walks past anything that is not a function, and a
    walk-past is how a surface stops being covered without anybody noticing. A
    callable object, a ``functools.partial``, a C function -- none exist on
    this package's public surface today, and this is what says so rather than
    assuming it. If one arrives, it comes back from here and the test that
    reads this fails, which is a decision somebody has to make rather than a
    gap somebody has to find.
    """
    odd: list[str] = []
    for members in namespaces.values():
        for name in sorted(members):
            if name.startswith("_"):
                continue
            obj = members[name]
            if inspect.isclass(obj) or inspect.isfunction(obj) or inspect.ismodule(obj):
                continue
            if callable(obj):
                odd.append(f"{name} ({type(obj).__name__})")
    return odd


def _surface_namespaces() -> dict[str, Mapping[str, object]]:
    """What a user imports: the package root, and the spec module beside it.

    ``pandid.__all__`` is every name the reference tells a reader to import
    bare -- ``tests/test_documented_types.py`` is what holds those two
    together. ``pandid.spec`` is the second door, named in full by the
    reference because it is not on the root.
    """
    return {
        "pandid": {name: getattr(pandid, name) for name in pandid.__all__},
        "pandid.spec": {
            name: value
            for name, value in vars(SPEC).items()
            if not name.startswith("_") and getattr(value, "__module__", None) == SPEC.__name__
        },
    }


def _function(obj: Any) -> Any:
    """The plain function behind a bound method, classmethod or staticmethod.

    ``Flowsheet.from_dict`` is a bound classmethod and is a *different object*
    from the function the enumeration keys on, so a case declaring it would
    have read as covering nothing at all -- which is how three of these entry
    points went missing on the first run of this file.
    """
    return getattr(obj, "__func__", obj)


def _qualified(func: Any) -> str:
    func = _function(func)
    return f"{func.__module__}.{func.__qualname__}"


# --------------------------------------------------------------------------
# The parametrisation
# --------------------------------------------------------------------------


def _pairs() -> list[tuple[str, str]]:
    return [(case.id, argument) for case in CASES.values() for argument in case.arguments]


PAIRS = _pairs()
CATCH_ALLS = [case.id for case in CASES.values() if case.entry and _has_catch_all(case.entry)]


# --------------------------------------------------------------------------
# The checks
# --------------------------------------------------------------------------


@pytest.mark.parametrize("case_id", sorted(CASES), ids=sorted(CASES))
def test_a_case_says_the_same_thing_twice(case_id: str) -> None:
    """The witness has to be stable, or nothing below means anything.

    A reading with a memory address, a clock or a temporary path in it differs
    from itself, every probe looks like a difference, and every argument in
    this file passes without being read. That is the exact shape of a guard
    that holds nothing, so it is checked first and for every case.
    """
    case = CASES[case_id]
    first, second = _outcome(case), _outcome(case)
    assert first == second, f"{case_id} does not describe itself the same way twice"


@pytest.mark.parametrize("case_id", sorted(CASES), ids=sorted(CASES))
def test_a_case_makes_its_baseline_call_without_raising(case_id: str) -> None:
    """A recipe whose ordinary call already fails cannot tell honoured from
    dropped: every probe would raise too, and every argument would pass."""
    outcome = _outcome(CASES[case_id])
    assert not outcome.startswith("raised"), f"{case_id}'s baseline call {outcome[:400]}"


def _code_objects_run(case: Case) -> set[Any]:
    """Every function *case*'s baseline call actually enters.

    A tracer rather than a reading of the recipe, because the recipe is what is
    in doubt. ``Vessel.nozzle`` is ``_MultiPortVessel.nozzle`` and not
    ``Unit.nozzle``: a case built on a vessel and labelled ``Unit.nozzle``
    would have discharged that entry point's coverage while never running a
    line of it, and nothing about the case would have looked wrong.
    """
    seen: set[Any] = set()

    def tracer(frame: Any, event: str, _arg: Any) -> None:
        if event == "call":
            seen.add(frame.f_code)
        return None

    previous = sys.gettrace()
    sys.settrace(tracer)
    try:
        _outcome(case)
    finally:
        sys.settrace(previous)
    return seen


TRACEABLE = sorted(cid for cid, case in CASES.items() if case.entry is not None)


@pytest.mark.parametrize("case_id", TRACEABLE, ids=TRACEABLE)
def test_a_case_runs_the_entry_point_it_says_it_covers(case_id: str) -> None:
    """Coverage of the public surface is discharged by cases, so a case that
    claims an entry point it does not reach is a hole in the surface that
    reads as covered."""
    case = CASES[case_id]
    entry = _function(case.entry)
    assert entry.__code__ in _code_objects_run(case), (
        f"{case_id} says it covers {_qualified(entry)} and never calls it"
    )


@pytest.mark.parametrize(("case_id", "argument"), PAIRS, ids=[f"{c}:{a}" for c, a in PAIRS])
def test_an_argument_that_is_accepted_is_capable_of_changing_something(
    case_id: str, argument: str
) -> None:
    """The rule of #495, one argument at a time.

    A failure here means the entry point took the word, drew the same sheet it
    would have drawn without it, and said nothing. Either the argument should
    be read, or the signature should not offer it -- and if it genuinely cannot
    apply in this configuration, that is a line in :data:`INAPPLICABLE` with a
    reason, not a deletion of this case.
    """
    case = CASES[case_id]
    declared = INAPPLICABLE.get((case_id, argument))
    honoured = _honoured(case, argument)
    if declared is None:
        assert honoured, (
            f"{case_id} accepts {argument}= and does the same thing whatever it is given. "
            f"If that is deliberate, declare it in INAPPLICABLE with the reason."
        )
        return
    assert not honoured, (
        f"INAPPLICABLE says {case_id} cannot act on {argument}=, and it did. "
        f"The declaration is out of date{' (' + declared.issue + ')' if declared.issue else ''}"
        f" -- delete the line."
    )


@pytest.mark.parametrize("case_id", sorted(CATCH_ALLS), ids=sorted(CATCH_ALLS))
def test_an_entry_point_with_a_catch_all_refuses_an_unknown_keyword(case_id: str) -> None:
    """``**opts`` may not mean accepted and dropped.

    #492 settled this for the two renderers -- the protocol needs the catch-all
    in the signature, so what had to change was what an unnamed keyword means.
    Every other entry point that grew one is held to the same rule here.
    """
    case = CASES[case_id]
    baseline = _outcome(case)
    poisoned = _outcome(case, **{UNKNOWN_KEYWORD: True})
    assert poisoned != baseline, (
        f"{case_id} accepted {UNKNOWN_KEYWORD}= through its catch-all and did nothing with it"
    )


# --------------------------------------------------------------------------
# The checks on the checking
# --------------------------------------------------------------------------


def stale_declarations(
    declared: Mapping[tuple[str, str], Inapplicable], cases: Mapping[str, Case]
) -> list[str]:
    """Every way a line of :data:`INAPPLICABLE` can have stopped meaning anything.

    A declaration naming a case that has been renamed, or an argument that has
    been removed, is a line nobody will ever read again -- and, worse, a line
    that is no longer excusing anything, so the reader who finds it believes a
    check is being made that is not.
    """
    complaints: list[str] = []
    for (case_id, argument), entry in sorted(declared.items()):
        case = cases.get(case_id)
        if case is None:
            complaints.append(f"{case_id}:{argument} names no case")
            continue
        if argument not in case.arguments:
            complaints.append(f"{case_id}:{argument} names no argument of that case")
        if len(entry.reason.split()) < 4:
            complaints.append(f"{case_id}:{argument} gives no reason worth reading")
        if entry.issue and not re.fullmatch(r"#\d+", entry.issue):
            complaints.append(f"{case_id}:{argument} cites {entry.issue!r}, which is not an issue")
    return complaints


def uncovered_surface(
    surface: Mapping[Any, list[str]], cases: Mapping[str, Case], unexercised: Mapping[str, str]
) -> tuple[list[str], list[str]]:
    """What the public surface has that nothing here accounts for, and the
    reverse: what is declared out of reach but is no longer on the surface."""
    exercised = {_function(case.entry) for case in cases.values() if case.entry is not None}
    missing = sorted(
        _qualified(func)
        for func in surface
        if func not in exercised and _qualified(func) not in unexercised
    )
    names = {_qualified(func) for func in surface}
    stale = sorted(name for name in unexercised if name not in names)
    return missing, stale


def test_every_public_entry_point_is_exercised_or_declared_out_of_reach() -> None:
    """The list of entry points is derived, never written.

    A hand-written list is the defect #495 is about: it was right the day it
    was typed and wrong the day the next keyword landed. This walks what the
    package exports, and a new public method fails here until somebody either
    writes it a case or says in :data:`UNEXERCISED` why one cannot be written.
    """
    surface = public_callables(_surface_namespaces())
    missing, stale = uncovered_surface(surface, CASES, UNEXERCISED)
    assert not missing, "no case calls these, and UNEXERCISED does not say why: " + ", ".join(
        missing
    )
    assert not stale, "UNEXERCISED names entry points the package no longer has: " + ", ".join(
        stale
    )


def test_the_public_surface_is_not_empty_and_holds_what_it_obviously_should() -> None:
    """A floor under the enumeration.

    If ``public_callables`` returned nothing, the test above would pass with
    nothing to say. These are the entry points #495 names by hand; finding them
    proves the walk reaches methods, classmethods, inherited overrides and
    module-level functions.
    """
    surface = {_qualified(func) for func in public_callables(_surface_namespaces())}
    for expected in (
        "pandid.flowsheet.Flowsheet.to_svg",
        "pandid.flowsheet.Flowsheet.render",
        "pandid.flowsheet.Flowsheet.show",
        "pandid.flowsheet.Flowsheet.layout",
        "pandid.flowsheet.Flowsheet.route",
        "pandid.flowsheet.Flowsheet.validate",
        "pandid.flowsheet.Flowsheet.connect",
        "pandid.flowsheet.Flowsheet.from_dict",
        "pandid.units.Unit.pin",
        "pandid.units.Unit.__init__",
        "pandid.units._Boundary.repeats",  # an override reached only through the MRO
        "pandid.spec.from_dict",
    ):
        assert expected in surface, f"the enumeration lost {expected}"
    assert len(surface) >= 80, f"the enumeration collapsed to {len(surface)} entry points"


def test_nothing_public_is_callable_in_a_shape_the_enumeration_walks_past() -> None:
    """The one silent skip in the walk, made loud."""
    assert unrecognised_callables(_surface_namespaces()) == []


def test_a_callable_of_an_unexpected_shape_is_reported() -> None:
    """...and the check that says so, shown to say it."""

    class Callable_:
        def __call__(self, thing: int) -> int:
            return thing

    assert unrecognised_callables({"stub": {"odd": Callable_()}}) == ["odd (Callable_)"]
    assert unrecognised_callables({"stub": {"Odd": Callable_}}) == []


def test_the_declarations_are_all_live() -> None:
    assert stale_declarations(INAPPLICABLE, CASES) == []


def test_every_declaration_that_cites_an_issue_says_which() -> None:
    """A defect parked in the table is parked with a number, so that fixing it
    has somewhere to be recorded and this line has something to be deleted
    alongside."""
    for (case_id, argument), entry in INAPPLICABLE.items():
        if entry.issue:
            assert re.fullmatch(r"#\d+", entry.issue), f"{case_id}:{argument}"


def test_there_is_something_to_check() -> None:
    """The parametrisation cannot be allowed to collapse quietly.

    Every test above is parametrised over what ``_parameters`` reads off a
    signature. A reader that returned nothing would empty the parametrisation
    and leave a green file that checks nothing, which is the failure this whole
    section exists to stop.
    """
    assert len(PAIRS) >= 250, f"only {len(PAIRS)} argument checks were built"
    assert len(CASES) >= 60, f"only {len(CASES)} cases were built"
    for expected in (
        ("to_svg[pfd]", "page_size"),
        ("to_svg[pfd]", "check"),
        ("Flowsheet.connect", "kind"),
        ("Unit.pin", "port"),
        ("spec:stream", "ends"),
        ("cli:draw", "border"),
    ):
        assert expected in PAIRS, f"the parametrisation lost {expected}"
    assert CATCH_ALLS, "no entry point with a catch-all was found to check"


# --- the fixtures that break each mechanism on purpose ------------------------


class _Swallower:
    """An entry point that takes an argument and does nothing with it."""

    def __init__(self) -> None:
        self.calls = 0

    def run(self, **_ignored: Any) -> str:
        self.calls += 1
        return "the same answer every time"


def _swallowing_case() -> Case:
    return Case(id="planted:swallower", arguments=("dropped",), run=_Swallower().run)


def _honouring_case() -> Case:
    def run(**overrides: Any) -> str:
        return f"read {overrides.get('honoured', 'nothing')!r}"

    return Case(id="planted:honourer", arguments=("honoured",), run=run)


def _truthy_only_case() -> Case:
    """Honours its argument, but only tells a falsy value from its default.

    ``if flag:`` where ``flag`` defaults to True: the alien probe is truthy and
    changes nothing, and only the falsy probe finds the branch. Dropping the
    second probe would make this look discarded, which is why both are used.
    """

    def run(**overrides: Any) -> str:
        flag = overrides.get("flag", True)
        return "on" if flag else "off"

    return Case(id="planted:truthy-only", arguments=("flag",), run=run)


def test_the_engine_reports_an_argument_that_is_swallowed() -> None:
    """The negative control. Without this, an engine that answered "honoured"
    to everything -- a comparison against the wrong baseline, a witness that
    always differs -- would leave every test above green."""
    assert _honoured(_swallowing_case(), "dropped") is False


def test_the_engine_reports_an_argument_that_is_read() -> None:
    """The positive control, for the opposite failure: an engine that answered
    "discarded" to everything would fail loudly rather than silently, but it
    would also make every INAPPLICABLE line look correct."""
    assert _honoured(_honouring_case(), "honoured") is True


def test_the_falsy_probe_is_what_finds_an_argument_whose_default_is_true() -> None:
    """Break the probe set and show a case fails.

    With both probes the planted case is honoured; with the alien alone -- the
    obvious single-probe design -- it reads as discarded, and every ``True``
    default in the package would need excusing in INAPPLICABLE.
    """
    case = _truthy_only_case()
    assert _honoured(case, "flag") is True
    alien_only = Case(id=case.id, arguments=case.arguments, run=case.run, probes=(PROBES[0],))
    assert _honoured(alien_only, "flag") is False


def test_a_witness_that_differs_from_itself_is_caught() -> None:
    """The determinism check, driven by a case that cannot say the same thing
    twice. Everything in this file rests on a stable witness."""
    counter = {"n": 0}

    def run(**_overrides: Any) -> str:
        counter["n"] += 1
        return f"reading {counter['n']}"

    case = Case(id="planted:restless", arguments=("anything",), run=run)
    assert _outcome(case) != _outcome(case)
    # ...and such a case would call every argument honoured, which is the harm.
    assert _honoured(case, "anything") is True


def test_a_declaration_naming_a_case_that_is_gone_is_reported() -> None:
    complaints = stale_declarations(
        {("no such case", "x"): Inapplicable("a reason of at least four words")}, CASES
    )
    assert complaints and "names no case" in complaints[0]


def test_a_declaration_naming_an_argument_that_is_gone_is_reported() -> None:
    complaints = stale_declarations(
        {("to_svg[pfd]", "no_such_argument"): Inapplicable("a reason of at least four words")},
        CASES,
    )
    assert complaints and "names no argument" in complaints[0]


def test_a_declaration_with_no_reason_is_reported() -> None:
    complaints = stale_declarations({("to_svg[pfd]", "border"): Inapplicable("dunno")}, CASES)
    assert complaints and "no reason" in complaints[0]


def test_a_declaration_citing_something_that_is_not_an_issue_is_reported() -> None:
    complaints = stale_declarations(
        {("to_svg[pfd]", "border"): Inapplicable("a reason of at least four words", issue="soon")},
        CASES,
    )
    assert complaints and "not an issue" in complaints[0]


def test_the_enumeration_finds_a_planted_entry_point() -> None:
    """The walk, driven by a namespace this test made up.

    A stub class with one public method and one private one: the public method
    must come back, the private one must not, and a method that takes no
    argument must not either -- there is nothing in it to poison.
    """

    class Planted:
        def takes_one(self, thing: int) -> int:
            return thing

        def takes_none(self) -> int:
            return 0

        def _private(self, thing: int) -> int:
            return thing

    Planted.__module__ = "pandid.planted"
    for method in (Planted.takes_one, Planted.takes_none, Planted._private):
        method.__module__ = "pandid.planted"

    found = public_callables({"stub": {"Planted": Planted}})
    labels = {label for labels in found.values() for label in labels}
    assert "Planted.takes_one" in labels
    assert "Planted.takes_none" not in labels
    assert "Planted._private" not in labels


def test_the_enumeration_reports_nothing_for_an_empty_namespace() -> None:
    """The other half: a walk that returned the world for any input would make
    the coverage test fail loudly, but a walk that returned nothing would make
    it pass silently. It does neither."""
    assert public_callables({"stub": {}}) == {}
    assert public_callables({"stub": {"_hidden": Flowsheet}}) == {}


def test_a_public_entry_point_nobody_calls_is_reported() -> None:
    """Break the coverage table and show a case fails.

    A planted entry point that no case calls and ``UNEXERCISED`` does not name
    must come back as missing; naming it must make that stop; and naming
    something that has gone must come back as stale.
    """

    def orphan(argument: int) -> int:
        return argument

    orphan.__module__ = "pandid.planted"
    name = _qualified(orphan)
    surface = {orphan: [name]}
    missing, stale = uncovered_surface(surface, CASES, {})
    assert missing == [name]
    missing, stale = uncovered_surface(surface, CASES, {name: "planted"})
    assert missing == [] and stale == []
    missing, stale = uncovered_surface(surface, CASES, {"pandid.gone.away": "planted"})
    assert stale == ["pandid.gone.away"]


def test_the_catch_all_check_can_tell_a_refusal_from_a_shrug() -> None:
    """The ``**kwargs`` half, on planted functions rather than on the package.

    One takes a catch-all and drops it, one refuses; the reader that decides
    which entry points are checked has to see the catch-all at all.
    """

    def shrugs(**_opts: Any) -> str:
        return "drawn"

    def refuses(**opts: Any) -> str:
        if opts:
            raise ValueError(f"does not take {sorted(opts)}")
        return "drawn"

    assert _has_catch_all(shrugs) and _has_catch_all(refuses)
    assert not _has_catch_all(lambda thing: thing)
    dropped = Case(id="planted:shrugs", arguments=(), run=lambda **kw: shrugs(**kw))
    kept = Case(id="planted:refuses", arguments=(), run=lambda **kw: refuses(**kw))
    assert _outcome(dropped, **{UNKNOWN_KEYWORD: True}) == _outcome(dropped)
    assert _outcome(kept, **{UNKNOWN_KEYWORD: True}) != _outcome(kept)


def test_a_case_that_never_calls_what_it_claims_is_reported() -> None:
    """Break the coverage-by-case link and show a case fails.

    ``entry`` is what discharges an entry point's coverage, and nothing about a
    recipe makes it true. One planted case names ``to_svg`` and never calls it;
    one names it and does.
    """
    absent = Case(
        id="planted:absent", arguments=(), run=lambda **_kw: "nothing", entry=Flowsheet.to_svg
    )
    present = Case(
        id="planted:present",
        arguments=(),
        run=lambda **kw: _sheet().to_svg(**kw),
        entry=Flowsheet.to_svg,
    )
    assert Flowsheet.to_svg.__code__ not in _code_objects_run(absent)
    assert Flowsheet.to_svg.__code__ in _code_objects_run(present)


def test_the_option_reader_reads_a_parser_this_test_made_up() -> None:
    """The CLI half of the enumeration, driven by a parser of its own, so a
    reader that came back empty could not make the option checks pass by having
    no options to check."""
    planted = argparse.ArgumentParser()
    planted.add_argument("thing")
    planted.add_argument("--flag", action="store_true")
    planted.add_argument("--valued", choices=("a", "b"))
    found = _cli_actions(planted)
    assert set(found) == {"thing", "flag", "valued"}
    assert _cli_actions(argparse.ArgumentParser(add_help=False)) == {}


def test_the_spec_key_reader_reads_a_table_this_test_made_up() -> None:
    """``_ANNOTATION_KEYS`` is a mapping of box type to keys and every other
    table names keys directly; reading the first one the second way would have
    covered five box types instead of thirty-eight keys."""
    assert _spec_keys("_SOMETHING_KEYS", {"a", "b"}) == {"a", "b"}
    assert _spec_keys("_SOMETHING_KEYS", {"a": ("Cls",), "b": ("Cls",)}) == {"a", "b"}
    assert _spec_keys("_ANNOTATION_KEYS", {"note": {"a", "b"}, "table": {"c"}}) == {"a", "b", "c"}


def test_the_command_line_surface_is_read_off_the_parser() -> None:
    """The CLI cases are only as good as the option list behind them."""
    subs = _cli_subcommands()
    assert set(subs) >= {"draw", "validate", "symbols"}
    draw = _cli_actions(subs["draw"])
    for expected in (
        "spec",
        "output",
        "page_size",
        "border",
        "diagram",
        "connections",
        "stream_table",
        "jump_direction",
        "crossing_style",
        "debug",
    ):
        assert expected in draw, f"the parser reader lost --{expected}"


#: The two ``*_KEYS`` tables in :mod:`pandid.spec` that are not lists of keys a
#: section accepts, and why. Named here rather than skipped in a condition, so
#: that a third one added tomorrow fails
#: :func:`test_the_spec_key_sets_are_all_covered_by_a_case` instead of being
#: quietly waved through by a rule that never mentioned it.
NOT_ALLOWED_KEY_SETS: dict[str, str] = {
    "_RETIRED_KEYS": (
        "keys the format no longer has: they are refused by name, which is the "
        "opposite of being read, and tests/test_spec.py holds that"
    ),
    "_ANCHOR_KEYS": (
        "the three ways an instrument entry names its anchor, all of them already "
        "in _INSTRUMENT_KEYS and probed there"
    ),
}


def _spec_keys(name: str, value: Any) -> set[str]:
    """The spec keys a ``*_KEYS`` table names.

    ``_ANNOTATION_KEYS`` maps a box type to the keys that type takes, so its
    keys are box types and its *values* are what a spec writes; every other
    table names the keys directly, whether it is a set or a mapping to the
    classes that may carry them.
    """
    if name == "_ANNOTATION_KEYS":
        return set().union(*(set(keys) for keys in value.values()))
    return set(value)


def test_the_spec_key_sets_are_all_covered_by_a_case() -> None:
    """The spec reader's surface is its allowed-key sets, and every one of them
    is a case here -- so a section that grows a key gets it probed, and a
    section added to the format fails this until it gets a case."""
    tables = {name: value for name, value in vars(SPEC).items() if name.endswith("_KEYS")}
    assert len(tables) >= 10, f"only {len(tables)} key sets were found"
    stale = sorted(name for name in NOT_ALLOWED_KEY_SETS if name not in tables)
    assert not stale, f"NOT_ALLOWED_KEY_SETS names tables pandid.spec no longer has: {stale}"
    covered: set[str] = set()
    for case in CASES.values():
        if case.id.startswith("spec:"):
            covered |= set(case.arguments)
    for name in sorted(tables):
        if name in NOT_ALLOWED_KEY_SETS:
            continue
        keys = _spec_keys(name, tables[name])
        assert keys, f"{name} names no keys at all"
        assert keys <= covered, f"{name} has keys no case probes: {sorted(keys - covered)}"


def test_every_settable_property_has_a_case() -> None:
    """The setters are a surface of their own, and it is derived too.

    A property that grows a setter is an entry point with one argument from
    that day, and this is what makes it one here.
    """
    found = _settable_properties(_property_namespace())
    assert len(found) >= 8, f"only {len(found)} settable properties were found"
    missing = sorted(cid for cid in found if cid not in CASES)
    assert not missing, f"these settable properties have no case: {missing}"


def test_the_property_reader_finds_a_planted_setter_and_no_read_only_one() -> None:
    """The reader driven by a namespace this test made up, for the same reason
    the enumeration is: a reader that came back empty would make the test above
    pass with nothing in it."""

    class Planted:
        @property
        def settable(self) -> int:
            return 0

        @settable.setter
        def settable(self, value: int) -> None:
            self._value = value

        @property
        def read_only(self) -> int:
            return 0

    found = _settable_properties({"Planted": Planted})
    assert set(found) == {"Planted.settable ="}
    assert _settable_properties({"Planted": SimpleNamespace()}) == {}
