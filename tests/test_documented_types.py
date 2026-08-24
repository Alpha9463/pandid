"""The documentation may not name a type the package root does not export.

``docs/api.md`` named ``ControlLoop`` as a return type three times and neither it
nor ``Loop`` nor ``ValveStation`` was importable from ``pandid`` (#441). A reader
who followed the reference exactly wrote ``from pandid import ControlLoop`` and
got an ``ImportError``: the documentation described an API the package did not
have. That is worse here than it looks, because this package ships ``py.typed``
and asks to be annotated against, and because #174 makes "correct on the first
try, from the documentation alone" a goal rather than a nicety.

The rule these tests hold both halves to is one a reader can check by eye:

    A type the documentation names **bare** is importable from ``pandid``.
    A type that is not is named with the module it lives in.

So ``Stream``, ``Port``, ``Loop`` and ``Issue`` are on the package, and
``pandid.state.State``, ``pandid.document.StreamTableOptions`` and
``pandid.render.symbols.Symbol`` -- three the package deliberately does not
export -- are written out in full wherever the reference mentions them. Either
spelling imports. Neither test cares which of the two an author picks; both fail
on the third possibility, which is the bug.

The rule is enforced rather than reviewed because the gap arrives one name at a
time. #441 was three names, and the sweep that answered it found twenty-two: no
one held them back, they simply arrived one helper at a time with nothing
checking. The next handle a helper returns will arrive the same way.

``CONTRIBUTING.md`` is deliberately not scanned. It documents the internals to
someone changing them -- ``OverlayPart``, ``Deprecation``, ``IsoPart`` -- and an
internal named there is a description of the machinery, not a promise about the
surface.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import re
from pathlib import Path
from typing import Callable

import pytest

import pandid

_REPO = Path(__file__).resolve().parent.parent

#: What a user reads and writes imports from. Every one is shipped in the sdist.
_USER_DOCS = ("docs/api.md", "README.md", "docs/gallery/README.md")

#: A class name: CamelCase, which every class in this package is.
_CLASS_NAME = re.compile(r"\b([A-Z][A-Za-z0-9]*)\b")

#: A fenced block's opening line, capturing its language.
_FENCE = re.compile(r"^```(\w*)\s*$")

#: One span between backticks, which is how prose spells anything typed.
_BACKTICKED = re.compile(r"`([^`\n]+)`")

#: A dotted module path under this package. The ``+`` is deliberate: a bare
#: ``pandid`` says nothing about where a class is and must not excuse one.
_DOTTED = re.compile(r"\bpandid(?:\.\w+)+\b")


#: One class per module the sweep below has to reach, and a class the module
#: really defines. A checker that cannot see reports nothing to fix, which reads
#: exactly like a clean run -- so the sweep is made to prove it looked. Every
#: module the twenty-two documented types came from is represented, the renderer
#: and the two extension packages included, because it is precisely the module
#: that stops importing whose classes then go unchecked.
_MUST_BE_FOUND = {
    "Flowsheet": "pandid.flowsheet",
    "Unit": "pandid.units",
    "Port": "pandid.ports",
    "Stream": "pandid.streams",
    "Frame": "pandid.geometry",
    "Loop": "pandid.loops",
    "ValveStation": "pandid.stations",
    "Issue": "pandid.validate",
    "TitleBlock": "pandid.document",
    "StreamTableOptions": "pandid.document",
    "State": "pandid.state",
    "Symbol": "pandid.render.symbols",
    "SymbolRegistry": "pandid.render.symbols",
    "ConstraintLayoutEngine": "pandid.layout",
    "DefaultRouter": "pandid.routing",
}


def _public_classes() -> dict[str, str]:
    """Every public class this package defines, mapped to its own module.

    Keyed by bare name because that is how the documentation writes it, and
    valued by ``__module__`` rather than by where it was imported, so a class
    re-exported into three namespaces is still one entry answering "where does
    this actually live".

    **Nothing is caught here.** An import that failed used to be skipped, and a
    skipped module is a module whose classes every check below then stops asking
    about -- so a broken ``pandid.render`` would have made a bare ``Symbol`` in
    the documentation pass. No module in this package needs an optional extra to
    import (the ``pdf`` extra is imported inside the function that rasterises,
    not at module scope), so an ``ImportError`` here is a broken package and has
    to be heard. Should one ever need an extra, catch *that module by name*
    rather than catching the class of error.

    ``_MUST_BE_FOUND`` is the other half of the same argument. Letting the error
    out covers the module that raises; it does not cover a walk that quietly
    reaches nothing, and an empty result would satisfy every check in this file.
    Only a positive claim about what was found tells a clean run from a blind
    one.
    """
    found: dict[str, str] = {}
    for module in pkgutil.walk_packages(pandid.__path__, "pandid."):
        imported = importlib.import_module(module.name)
        for name, value in vars(imported).items():
            if name.startswith("_") or not inspect.isclass(value):
                continue
            if getattr(value, "__module__", "").startswith("pandid."):
                found[name] = value.__module__

    unseen = {name: module for name, module in _MUST_BE_FOUND.items() if found.get(name) != module}
    assert not unseen, (
        "the sweep over pandid did not reach classes it must reach, so every "
        f"check built on it is answering about a package it could not read: {unseen}"
    )
    return found


def _module_prefixes(line: str) -> set[str]:
    """Every module path a dotted path on this line passes *through*.

    ``pandid.render.symbols.SymbolRegistry.for_unit`` passes through
    ``pandid.render.symbols`` and so names it, and a class living there is
    placed by it. The trailing components produce entries that are not modules
    at all, which is harmless: the caller only ever matches these against a real
    ``__module__``.

    The direction matters and only one of the two is admissible. A path that
    reaches *past* a module names it. A path that stops *short* of it --
    ``pandid.render`` for a class in ``pandid.render.symbols`` -- does not, and
    used to be accepted here. A reader given ``pandid.render`` still cannot
    write the import, which is the whole thing being checked.
    """
    prefixes: set[str] = set()
    for path in _DOTTED.findall(line):
        parts = path.split(".")
        for stop in range(2, len(parts) + 1):
            prefixes.add(".".join(parts[:stop]))
    return prefixes


def _public_members(cls: type) -> dict[str, object]:
    """``cls``'s public methods and properties, **inherited ones included**.

    ``vars(cls)`` was wrong here and quietly so. Almost every documented method
    is declared on a base -- ``pin()`` and ``nozzle()`` on ``Unit``, so
    ``Pump.pin`` -- and reading only the subclass's own namespace meant the
    check ran over a handful of overrides and skipped the surface a caller
    actually uses.

    The MRO is walked instead of ``inspect.getmembers()`` because getmembers
    fetches through the descriptor protocol, which runs every property's getter
    on the class object. Walking ``__mro__`` and reading each base's ``vars()``
    gets the descriptor itself. First writer wins, so an override is checked and
    the definition it hides is not, which is what the caller sees. Bases outside
    this package (``object``, ``Protocol``) are skipped: their docstrings are not
    this project's promises.
    """
    members: dict[str, object] = {}
    for base in cls.__mro__:
        if not getattr(base, "__module__", "").startswith("pandid"):
            continue
        for name, member in vars(base).items():
            if not name.startswith("_") and name not in members:
                members[name] = member
    return members


def _names_a_module(line: str, name: str, module: str) -> bool:
    """Does this line say where ``name`` lives?

    Either as the class's own full path (``pandid.document.StreamTableOptions``)
    or as its module, which is how the reference annotates the two extension
    protocols: ``class Router(Protocol):  # pandid.routing``.
    """
    if re.search(rf"\bpandid(?:\.\w+)*\.{re.escape(name)}\b", line):
        return True
    return module in _module_prefixes(line)


def _type_mentions(text: str) -> list[tuple[int, str, str]]:
    """``(line number, name, whole line)`` for every type name the text spells.

    Two places count, and they are the two a reader lifts an import from:

    * a **backticked span** in prose, which is how this reference writes
      anything typed -- a table's Type column, ``list[Issue]``, ``a `Stream```;
    * every line of a ``text`` fence, which is where the signature blocks are,
      and where a return type is named with no backticks around it.

    A ``python`` fence is not scanned. It is a runnable example, so it carries
    its own import line, and its string literals are prose -- ``units.Block("Synthesis
    Loop")`` is not a mention of ``Loop``. Unfenced prose outside backticks is
    not scanned for the same reason in reverse: "the Port table" is English.
    """
    mentions: list[tuple[int, str, str]] = []
    language: str | None = None
    for number, line in enumerate(text.splitlines(), 1):
        opening = _FENCE.match(line)
        if opening is not None and language is None:
            language = opening.group(1) or "plain"
            continue
        if language is not None and line.strip() == "```":
            language = None
            continue
        if language is None:
            spans = _BACKTICKED.findall(line)
        elif language == "text":
            spans = [line]
        else:
            continue
        for span in spans:
            for name in _CLASS_NAME.findall(span):
                mentions.append((number, name, line))
    return mentions


def _documented_names() -> set[str]:
    """Every class name the user-facing documents spell, package membership aside.

    Deliberately not filtered against what ``pandid`` currently defines, which is
    what makes it the rename guard's eye. Every other check here starts from the
    package's own class names and asks the documentation about them, so a class
    the package no longer has is a question none of them think to ask -- and a
    reference still saying ``-> ControlLoop`` after the rename reads as clean.
    This looks the other way down the same road.
    """
    seen: set[str] = set()
    for relative in _USER_DOCS:
        text = (_REPO / relative).read_text(encoding="utf-8")
        seen.update(name for _, name, _ in _type_mentions(text))
    return seen


def _documented_but_unreachable(exported: Callable[[str], bool]) -> list[str]:
    """Every place the docs name a class that ``exported`` says is not on the root.

    Takes the export test as an argument so the last test in this file can hand
    it a smaller ``__all__`` and prove these two actually fail. A name is
    reported unless the line it is on says which module it lives in.
    """
    classes = _public_classes()
    failures: list[str] = []
    for relative in _USER_DOCS:
        path = _REPO / relative
        for number, name, line in _type_mentions(path.read_text(encoding="utf-8")):
            module = classes.get(name)
            if module is None or exported(name):
                continue
            if _names_a_module(line, name, module):
                continue
            failures.append(f"{relative}:{number}: `{name}` ({module}) -- {line.strip()}")
    return failures


def test_every_type_the_documentation_names_is_importable_from_the_root():
    """The guard #441 asks for: fix it once and it stays fixed.

    Both halves of the rule are honoured here, so a name may be added either
    way. Exporting it is right when a reader holds the object -- ``connect()``
    hands back a :class:`~pandid.streams.Stream`, ``validate()`` a list of
    :class:`~pandid.validate.Issue`. Writing the module out is right when the
    class is machinery the reader never types: nothing constructs a
    :class:`~pandid.document.StreamTableOptions` (every flowsheet has one) and
    nothing builds a second symbol registry.
    """
    failures = _documented_but_unreachable(lambda name: name in pandid.__all__)
    assert not failures, (
        "the documentation names types that `import pandid` cannot reach.\n"
        "Either export the name from pandid/__init__.py, or write the module "
        "out at the mention:\n  " + "\n  ".join(failures)
    )


def test_every_import_the_documentation_writes_is_an_import_that_works():
    """The other half: an example's own ``from pandid...`` line has to run.

    ``_type_mentions()`` skips ``python`` fences because an example carries its
    import, which is only an argument while the import is real. This is the
    check that makes it real, and it covers the non-types too -- a page that
    tells a reader to import ``equipment_list`` from a module without one sends
    them to the same ``ImportError`` by a different route.
    """
    written = re.compile(r"^\s*from\s+(pandid[\w.]*)\s+import\s+([^\n#]+)$", re.M)
    failures: list[str] = []
    for relative in _USER_DOCS:
        text = (_REPO / relative).read_text(encoding="utf-8")
        for match in written.finditer(text):
            module_name, imported = match.group(1), match.group(2)
            module = importlib.import_module(module_name)
            for name in (part.strip() for part in imported.split(",")):
                if name and not hasattr(module, name):
                    failures.append(f"{relative}: from {module_name} import {name}")
    assert not failures, "the documentation writes imports that fail:\n  " + "\n  ".join(failures)


def test_every_type_a_public_return_or_docstring_names_is_reachable_too():
    """The source side of the same rule, where the next gap will start.

    A documented type gets into ``docs/api.md`` because a signature grew it
    first: #441 is three names that arrived as ``-> ControlLoop``, ``-> Loop``
    and ``-> ValveStation`` and were written up from there. So the two things a
    caller is actually *told* are checked here -- what a public method hands
    back, and what its docstring says, which is the copy of the reference that
    ``help()`` prints. Both spellings pass, as above:
    ``Flowsheet.add_valve_station`` returns a bare ``ValveStation`` and that name
    is on the package, while ``Block.symbol`` returns a ``Symbol`` and names
    ``pandid.render.symbols`` in the same docstring.

    Parameter and field annotations are deliberately not checked.
    ``Port.state`` is annotated ``State | None`` against ``pandid/ports.py``'s
    own import: that is a description of storage rather than a promise to a
    caller, and the reference already writes that one out in full as
    ``pandid.state.State``. What such an annotation has to do is *resolve*, and
    ``mypy pandid`` is the gate that owns it.
    """
    classes = _public_classes()
    failures: list[str] = []

    def authored_doc(fn: object) -> str:
        """``fn``'s docstring, unless the docstring is the field list again.

        A ``@dataclass`` with no docstring of its own is given one by the
        decorator: the constructor signature, field annotations and all. That is
        the annotations this test has just said it does not read, arriving by a
        second door, so it is dropped rather than answered.
        """
        doc = inspect.getdoc(fn) or ""
        if inspect.isclass(fn) and doc.startswith(fn.__name__ + "("):
            return ""
        return doc

    def check(owner: str, fn: object) -> None:
        returns = str((getattr(fn, "__annotations__", None) or {}).get("return", ""))
        spelled = returns + " " + authored_doc(fn)
        for name in sorted(set(_CLASS_NAME.findall(spelled))):
            module = classes.get(name)
            if module is None or name in pandid.__all__:
                continue
            if _names_a_module(spelled, name, module):
                continue
            failures.append(f"{owner}: `{name}` ({module})")

    for exported_name in pandid.__all__:
        value = getattr(pandid, exported_name)
        if inspect.isfunction(value):
            check(f"pandid.{exported_name}", value)
        if not inspect.isclass(value):
            continue
        check(exported_name, value)
        for member_name, member in _public_members(value).items():
            if inspect.isfunction(member):
                check(f"{exported_name}.{member_name}", member)
            elif isinstance(member, property) and member.fget is not None:
                check(f"{exported_name}.{member_name}", member.fget)

    assert not failures, (
        "public return types and docstrings name types `import pandid` cannot reach:\n  "
        + "\n  ".join(failures)
    )


# ---------------------------------------------------------------------------
# The guard's own guard
# ---------------------------------------------------------------------------


#: The thirteen #441 put on the package: every type ``docs/api.md`` names as
#: something the reader is handed. Listed here rather than derived, because a
#: derived list would re-derive the very thing it is checking and would go quiet
#: the day one of them stopped being documented.
#: Each handle beside the module that defines it. Written as a pair rather than
#: a bare name because "is it exported" and "is it the class the reference
#: describes" are two questions, and only the second catches a re-export that
#: has gone stale. ``pandid.Port = object`` answers the first perfectly.
_HANDLES = (
    ("Port", "pandid.ports"),
    ("Stream", "pandid.streams"),
    ("Pin", "pandid.geometry"),
    ("Frame", "pandid.geometry"),
    ("Route", "pandid.geometry"),
    ("Loop", "pandid.loops"),
    ("ControlLoop", "pandid.loops"),
    ("ValveStation", "pandid.stations"),
    ("Issue", "pandid.validate"),
    ("TitleBlock", "pandid.document"),
    ("Revision", "pandid.document"),
    ("Annotation", "pandid.document"),
    ("TableBox", "pandid.document"),
)


@pytest.mark.parametrize("name, module", _HANDLES)
def test_a_handle_is_the_documented_class_and_stays_documented(name: str, module: str):
    """Four questions about one name, because each fails in its own way.

    A guard that only ever passes is a guard nobody has seen work, so three of
    these four are run against a mutation of the thing they check.

    1. **Exported.** The decision itself: ``connect()`` hands back a ``Stream``
       and ``fs.warnings`` is a list of ``Issue``, so both are names a reader
       annotates with and both are on the root.
    2. **Bound to the class the reference describes.** ``pandid.Port`` has to
       *be* ``pandid.ports.Port``, not merely be present. Presence is what
       ``hasattr`` asked, and ``hasattr`` is satisfied by a re-export that has
       gone stale in a refactor and by a name rebound to anything at all --
       which is #441 again, one step further along: the import succeeds and
       hands back something that is not the documented type.
    3. **Still named in the documentation.** A rename is the failure neither of
       the two above sees. Rename ``ControlLoop`` and update ``__init__.py`` and
       this table, and the documentation check goes quiet -- it only asks about
       names the package still has, and ``ControlLoop`` is no longer one of
       them, so a reference full of ``-> ControlLoop`` reads as clean. This is
       the assertion that fails in that case.
    4. **Removal is caught.** The documentation check, run against an ``__all__``
       this name has been taken out of, has to come back naming the file and the
       line -- which is the whole of what #441 needed and did not have.
    """
    assert name in pandid.__all__, f"{name} is documented as a handle and is not exported"

    documented_class = getattr(importlib.import_module(module), name)
    assert getattr(pandid, name, None) is documented_class, (
        f"pandid.{name} is not {module}.{name}. A name in `__all__` bound to "
        "anything else imports cleanly and hands the reader the wrong type, "
        "which is the bug in #441 with an extra step."
    )

    assert name in _documented_names(), (
        f"{name} is exported as a handle and no user-facing document names it. "
        "A rename that reached the code and not the reference leaves the "
        "documentation naming a type that no longer exists, which every check "
        "keyed on the package's own class names is blind to."
    )

    smaller = set(pandid.__all__) - {name}
    failures = _documented_but_unreachable(lambda candidate: candidate in smaller)
    assert any(
        failure.startswith("docs/api.md:") and f"`{name}`" in failure for failure in failures
    ), f"removing {name} from __all__ went unnoticed: {failures}"


def test_every_exported_class_is_the_class_it_is_named_after():
    """The same identity question over all 142 exports, not just the thirteen.

    ``__all__`` is built from ``units.__all__`` and ``devices.__all__``, two
    lists this file does not own, so the cheap invariant is worth stating over
    the whole of it: every exported class is defined in this package and carries
    the name it is exported under. A star import that shadowed one, or a
    re-export left pointing at a renamed class, breaks one of the two.
    """
    wrong: list[str] = []
    for name in pandid.__all__:
        value = getattr(pandid, name, None)
        if value is None or inspect.ismodule(value) or not inspect.isclass(value):
            continue
        if not getattr(value, "__module__", "").startswith("pandid."):
            wrong.append(f"pandid.{name} is {value!r}, which this package did not define")
        elif value.__name__ != name:
            wrong.append(f"pandid.{name} is {value.__module__}.{value.__name__}")
    assert not wrong, "exported names bound to the wrong class:\n  " + "\n  ".join(wrong)


def test_the_rename_guard_can_tell_a_documented_name_from_one_that_is_not():
    """``_documented_names()`` is the rename guard's eye; here it is shown to work.

    If it answered "yes" to everything the assertion it backs would be
    decoration, so it is asked about a spelling the reference has never used --
    the one a rename of ``ControlLoop`` might plausibly introduce.
    """
    documented = _documented_names()
    assert "ControlLoop" in documented
    assert "ControlScheme" not in documented


def test_the_check_reads_prose_and_signatures_and_not_string_literals():
    """What ``_type_mentions()`` counts, pinned so a later widening is deliberate.

    The scan is narrow on purpose -- backticked prose and ``text`` fences -- and
    a scan that quietly grew to unfenced prose would start demanding an export
    for every English word that happens to be a class name.
    """
    sample = "\n".join(
        [
            "The Port table lists them.",
            "`connect()` returns a `Stream`.",
            "```text",
            "add_loop(variable: str) -> Loop",
            "```",
            "```python",
            'fs.add(units.Block("Synthesis Loop"))',
            "```",
        ]
    )
    assert {name for _, name, _ in _type_mentions(sample)} == {"Stream", "Loop"}
