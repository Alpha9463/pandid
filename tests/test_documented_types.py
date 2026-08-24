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

**A note on what this file may not do.** A guard is a filter, and a filter's
blind spots live in the cases it declines to look at. Every ``continue``, every
``if not``, every narrowing of a set here is a defect this file has decided not
to catch, so each one carries the argument for why. Three rounds of review found
five such holes -- a wrong binding that was merely *present*, a documented name
resolving to nothing, an unimportable module reported as a clean sweep, public
classmethods never read, and a hand-maintained list of modules that could not
know about a module added tomorrow. What replaced them is the pattern to keep:
prefer a derived set over a written one, and prefer failing to skipping.
"""

from __future__ import annotations

import ast
import builtins
import importlib
import inspect
import pkgutil
import re
from pathlib import Path
from types import ModuleType
from typing import Callable

import pytest

import pandid

_REPO = Path(__file__).resolve().parent.parent
_PACKAGE = Path(pandid.__file__).resolve().parent

#: What a user reads and writes imports from. Every one is shipped in the sdist.
#: ``CONTRIBUTING.md`` is deliberately absent: it documents the internals to
#: someone changing them -- ``OverlayPart``, ``Deprecation``, ``IsoPart`` -- and
#: an internal named there describes the machinery rather than promising a
#: surface.
_USER_DOCS = ("docs/api.md", "README.md", "docs/gallery/README.md")

#: A class name: CamelCase, which every class in this package is.
_CLASS_NAME = re.compile(r"\b([A-Z][A-Za-z0-9]*)\b")

#: A name of two or more capitalised words -- ``ControlLoop``, ``TitleBlock``.
#: Prose is full of single tokens that are not types (the tag ``CV-305``, the
#: page size ``A3``, the service code ``CWS``), and no rule tells those from a
#: one-word class name. Two words is the shape that does, and it is the shape a
#: renamed class keeps.
_MULTIWORD_NAME = re.compile(r"\b([A-Z][a-z]+(?:[A-Z][a-z0-9]*)+)\b")

#: A fenced block's opening line, capturing its language.
_FENCE = re.compile(r"^```(\w*)\s*$")

#: One span between backticks, which is how prose spells anything typed.
_BACKTICKED = re.compile(r"`([^`\n]+)`")

#: A dotted module path under this package. The ``+`` is deliberate: a bare
#: ``pandid`` says nothing about where a class is and must not excuse one.
_DOTTED = re.compile(r"\bpandid(?:\.\w+)+\b")

#: Types from outside this package that the reference names. Everything else it
#: names has to be either a class this package declares or a builtin, so this is
#: the whole of the escape hatch and it is three names long. A fourth belongs
#: here only when the reference really does hand a reader a stdlib type.
_FOREIGN_TYPES = frozenset({"Path", "Callable", "Protocol"})


# ---------------------------------------------------------------------------
# What the package contains
# ---------------------------------------------------------------------------


def _modules_on_disk() -> set[str]:
    """Every importable module under ``pandid/``, read off the filesystem.

    The filesystem is the authority a hand-written list cannot be. A module
    added tomorrow is in this set the moment it is saved, which is the property
    the list it replaced did not have: that list passed happily while the walk
    skipped a module it had never heard of.
    """
    names: set[str] = set()
    for path in _PACKAGE.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        parts = list(path.relative_to(_PACKAGE).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        if not parts:
            # pandid/__init__.py is the package itself, which walk_packages
            # enumerates *within* rather than yielding. It is already imported.
            continue
        names.add("pandid." + ".".join(parts))
    return names


def _walked_modules() -> dict[str, ModuleType]:
    """Import every module under ``pandid`` and prove the walk reached them all.

    **Nothing is caught.** An import that failed used to be skipped, and a
    skipped module is a module whose classes every check below then stops asking
    about -- so a broken ``pandid.render`` would have made a bare ``Symbol`` in
    the documentation pass. No module in this package needs an optional extra to
    import (the ``pdf`` extra is imported inside the function that rasterises,
    not at module scope), so an ``ImportError`` here is a broken package and has
    to be heard. Should one ever need an extra, catch *that module by name*
    rather than catching the class of error.

    Letting the error out covers the module that raises. It does not cover a
    walk that quietly enumerates fewer modules than exist, which would satisfy
    every check in this file, so the two sets are compared. Both directions are
    checked: on disk and not walked is the blind spot, walked and not on disk
    means this function's own derivation has drifted from ``pkgutil``'s.
    """
    imported = {
        info.name: importlib.import_module(info.name)
        for info in pkgutil.walk_packages(pandid.__path__, "pandid.")
    }
    on_disk = _modules_on_disk()
    assert set(imported) == on_disk, (
        "the sweep over pandid did not see the package that is on disk, so every "
        "check built on it is answering about a smaller package than the one "
        f"shipped. Missed: {sorted(on_disk - set(imported))}. "
        f"Unexpected: {sorted(set(imported) - on_disk)}"
    )
    return imported


def _public_classes() -> dict[str, str]:
    """Every public class this package defines **at run time**, and its module.

    Keyed by bare name because that is how the documentation writes it, and
    valued by ``__module__`` rather than by where it was imported, so a class
    re-exported into three namespaces is still one entry answering "where does
    this actually live".

    Run time is the point: this is the set the export rule can apply to, because
    only a class that exists when Python runs can be imported from ``pandid``.
    The ``TYPE_CHECKING``-only narrowing classes are deliberately not here; see
    :func:`_declared_class_names`.
    """
    found: dict[str, str] = {}
    for imported in _walked_modules().values():
        for name, value in vars(imported).items():
            if name.startswith("_") or not inspect.isclass(value):
                continue
            if getattr(value, "__module__", "").startswith("pandid."):
                found[name] = value.__module__
    return found


def _declared_class_names() -> set[str]:
    """Every public class name this package's **source** declares.

    Parsed rather than imported, because a third of the narrowing classes the
    reference names do not exist at run time: ``Absorber2``, ``Column2`` and
    ``ColumnDraw1`` .. ``ColumnDraw8`` are declared inside ``if TYPE_CHECKING:``
    in ``pandid/units.py``, for a type checker to resolve ``n_feeds=2`` with.
    They are real names the documentation is right to use and a runtime sweep
    can never see, so "does this documented name exist at all" is asked of the
    source and "must this documented name be exported" is asked of the run time.

    ``ast`` rather than a regex: a regex over source finds ``class`` in a
    docstring and misses one behind a decorator, and this set is what decides
    whether a documented name is a typo.
    """
    names: set[str] = set()
    for path in _PACKAGE.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
                names.add(node.name)
    return names


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
    gets the descriptor itself, classmethods included. First writer wins, so an
    override is checked and the definition it hides is not, which is what the
    caller sees. Bases outside this package (``object``, ``Protocol``) are
    skipped: their docstrings are not this project's promises.
    """
    members: dict[str, object] = {}
    for base in cls.__mro__:
        if not getattr(base, "__module__", "").startswith("pandid"):
            continue
        for name, member in vars(base).items():
            if not name.startswith("_") and name not in members:
                members[name] = member
    return members


def _documentation_bearing(member: object) -> object | None:
    """The function behind a member, or ``None`` if the member carries no prose.

    Unwrapping is the point: ``Flowsheet.from_dict`` is a ``classmethod``, and a
    classmethod object has neither the annotations nor the docstring of the
    function inside it. Reading the descriptor and not the function is how the
    three documented constructors -- ``from_dict``, ``from_json``,
    ``from_yaml``, the first thing an engineer reaches for -- went unscanned.

    ``None`` for anything else, and that is the one narrowing here. A class
    attribute that is a ``str``, a ``list`` or a ``dict`` (``PORTS``, ``PLACES``,
    ``kind``) has no annotations of its own and no docstring of its own -- ask
    ``inspect.getdoc`` for one and it answers with ``str``'s, several hundred
    words about the builtin. It is a value, not a promise about a type, so there
    is nothing here for this file to read.
    """
    if isinstance(member, (classmethod, staticmethod)):
        return member.__func__
    if isinstance(member, property):
        return member.fget
    if inspect.isfunction(member):
        return member
    return None


# ---------------------------------------------------------------------------
# What the documentation says
# ---------------------------------------------------------------------------


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
    its own import line -- which
    ``test_every_import_the_documentation_writes_is_an_import_that_works``
    executes, so that is an argument backed by a check rather than a hope -- and
    its string literals are prose: ``units.Block("Synthesis Loop")`` is not a
    mention of ``Loop``. Unfenced prose outside backticks is not scanned for the
    mirror-image reason: "the Port table" is English.
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


def _type_positions(text: str) -> list[tuple[int, str, str]]:
    """Where the text is unambiguously naming a type, rather than mentioning one.

    Two positions, and between them they cover every way #441 presented:

    * ``-> T`` in a ``text`` fence. This is the shape the bug had -- three
      helpers returning ``ControlLoop``, ``Loop`` and ``ValveStation``.
    * a cell in a table column whose header is literally ``Type``. This is where
      ``StreamTableOptions`` and ``Route`` are named, and finding the column by
      its heading rather than by its position is what keeps the *value* columns
      out: this reference has tables whose second cell holds ``FC``/``FO``,
      ``A4``/``A3``, ``P``/``FB``/``CWS``, none of which is a type.

    Kept separate from :func:`_type_mentions` because the demand made here is
    stronger -- a name in one of these positions has to *resolve* -- and a
    stronger demand may only be made where the reading is certain.
    """
    positions: list[tuple[int, str, str]] = []
    language: str | None = None
    type_column: int | None = None
    for number, line in enumerate(text.splitlines(), 1):
        opening = _FENCE.match(line)
        if opening is not None and language is None:
            language = opening.group(1) or "plain"
            continue
        if language is not None and line.strip() == "```":
            language = None
            continue

        if language == "text":
            for returns in re.findall(r"->\s*([^#\n]+)", line):
                for name in _CLASS_NAME.findall(returns):
                    positions.append((number, name, line))
            continue
        if language is not None:
            continue

        if not line.lstrip().startswith("|"):
            type_column = None
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if "Type" in cells:
            type_column = cells.index("Type")
            continue
        if type_column is not None and type_column < len(cells):
            for span in _BACKTICKED.findall(cells[type_column]):
                for name in _CLASS_NAME.findall(span):
                    positions.append((number, name, line))
    return positions


def _prose_class_mentions(text: str) -> list[tuple[int, str, str]]:
    """Backticked two-word CamelCase in prose -- a name that can only be a class.

    ``ControlLoop``, ``TitleBlock``, ``StreamTableOptions``: nothing else in this
    reference is spelled that way. One-word names are not asked to resolve,
    because ``CWSH``, ``A1A`` and ``Debutaniser`` are spelled that way too and no
    rule separates them from ``Loop``. That is a real limit and it is the reason
    :func:`_type_positions` exists: a one-word class name still has to resolve
    wherever the text is actually naming a type.
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
        if language is not None:
            continue
        for span in _BACKTICKED.findall(line):
            for name in _MULTIWORD_NAME.findall(span):
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

    Takes the export test as an argument so the mutation tests below can hand it
    a smaller ``__all__`` and prove this actually fails. A name is reported
    unless the line it is on says which module it lives in.
    """
    classes = _public_classes()
    failures: list[str] = []
    for relative in _USER_DOCS:
        path = _REPO / relative
        for number, name, line in _type_mentions(path.read_text(encoding="utf-8")):
            module = classes.get(name)
            if module is None:
                # Not a class this package defines at run time, so the export
                # rule has nothing to say about it: a builtin (`ValueError`), one
                # of the three foreign types, or a TYPE_CHECKING-only narrowing
                # class (`ColumnDraw1`), none of which can be imported from
                # `pandid` at run time and none of which should be.
                #
                # That it is one of those and *not* a name that resolves to
                # nothing is asserted by
                # test_every_type_the_documentation_names_resolves_to_something.
                # Without that sibling, this line is where a documented type
                # renamed in the code and left stale in the reference would
                # vanish -- input accepted, found unusable, silently dropped.
                continue
            if exported(name):
                continue
            if _names_a_module(line, name, module):
                continue
            failures.append(f"{relative}:{number}: `{name}` ({module}) -- {line.strip()}")
    return failures


# ---------------------------------------------------------------------------
# The rule
# ---------------------------------------------------------------------------


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


def test_every_type_the_documentation_names_resolves_to_something():
    """A documented type has to exist. This is the check that says so.

    The likeliest real defect in a reference this size is not a missing export;
    it is a rename that reached the code and half the mentions. Every other check
    in this file starts from a name the package has and asks the documentation
    about it, so a name the package *stopped* having is one none of them look
    for -- ``| stream_table | StreamOptions |`` and ``-> RegulatoryLoop`` both
    read as perfectly clean, because no class of either name exists to be
    unexported.

    A name has to resolve to one of three things, and there is no fourth:

    * a class this package's source declares, run time or ``TYPE_CHECKING``;
    * a builtin, which is how ``ValueError`` and ``KeyError`` are named;
    * one of the three foreign types in ``_FOREIGN_TYPES``.

    Asked only where the reading is certain -- a return position, a ``Type``
    column, or a two-word CamelCase name in backticks -- because prose is full
    of ``CV-305`` and ``A1A`` and no rule tells those from a one-word class.
    """
    declared = _declared_class_names()
    failures: list[str] = []
    for relative in _USER_DOCS:
        text = (_REPO / relative).read_text(encoding="utf-8")
        for number, name, line in _type_positions(text) + _prose_class_mentions(text):
            if name in declared or name in _FOREIGN_TYPES:
                continue
            if hasattr(builtins, name):
                continue
            failures.append(f"{relative}:{number}: `{name}` resolves to nothing -- {line.strip()}")
    assert not failures, (
        "the documentation names types that do not exist. A rename that reached "
        "the code and not the reference looks exactly like this:\n  " + "\n  ".join(failures)
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

    Methods, properties **and classmethods**: ``Flowsheet.from_dict``,
    ``from_json`` and ``from_yaml`` are the documented constructors an engineer
    reaches for first, and reading the descriptor rather than the function
    inside it left all three unread.

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
                # Not a runtime class of this package's, or already on the root.
                # The first case is the sibling of the skip in
                # `_documented_but_unreachable`, and is narrower here: a name in
                # a docstring that resolves to nothing is a stale cross-
                # reference, which `pandid/` being Pyright- and mypy-clean does
                # not catch but which costs a reader nothing to follow.
                continue
            if _names_a_module(spelled, name, module):
                continue
            failures.append(f"{owner}: `{name}` ({module})")

    for exported_name in pandid.__all__:
        value = getattr(pandid, exported_name)
        if inspect.isfunction(value):
            check(f"pandid.{exported_name}", value)
        if not inspect.isclass(value):
            # A module (`units`, `devices`) or `__version__`: no return type and
            # no docstring of this project's own. That each is the *right*
            # object rather than merely present is
            # test_every_exported_name_is_bound_to_the_object_it_names.
            continue
        check(exported_name, value)
        for member_name, member in _public_members(value).items():
            fn = _documentation_bearing(member)
            if fn is not None:
                check(f"{exported_name}.{member_name}", fn)

    assert not failures, (
        "public return types and docstrings name types `import pandid` cannot reach:\n  "
        + "\n  ".join(failures)
    )


# ---------------------------------------------------------------------------
# The bindings behind the names
# ---------------------------------------------------------------------------

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

#: The three the package exported before #441, on the same footing.
_CORE = (
    ("Flowsheet", "pandid.flowsheet"),
    ("Component", "pandid.components"),
    ("SpecError", "pandid.spec"),
)


def _expected_bindings() -> dict[str, object]:
    """What every name in ``__all__`` has to *be*, derived from where it comes from.

    The unit and device names are not listed: ``__all__`` takes them from
    ``units.__all__`` and ``devices.__all__``, so this reads them from the same
    two modules and the mapping stays in step with a class added tomorrow. The
    sixteen that are not from those two lists are named, because they are the
    ones ``pandid/__init__.py`` imports by hand and so the ones a refactor can
    leave pointing somewhere else.

    ``__version__`` is absent deliberately: it is a string defined in
    ``pandid/__init__.py`` itself, so there is no second object to compare it
    against. Its caller checks it is a non-empty ``str`` and
    ``tests/test_packaging.py`` owns its format.
    """
    units_module = importlib.import_module("pandid.units")
    devices_module = importlib.import_module("pandid.devices")

    expected: dict[str, object] = {"units": units_module, "devices": devices_module}
    for name in units_module.__all__:
        expected[name] = getattr(units_module, name)
    for name in devices_module.__all__:
        expected[name] = getattr(devices_module, name)
    for name, module in _CORE + _HANDLES:
        expected[name] = getattr(importlib.import_module(module), name)
    return expected


def test_every_exported_name_is_bound_to_the_object_it_names():
    """Not "is it there" -- "is it the thing the reference describes".

    ``hasattr`` was the first version of this and a name rebound to anything at
    all satisfied it. Identity that *declines to look* at non-classes was the
    second, and ``pandid.Pump = None``, ``pandid.Pump = lambda: None`` and a
    look-alike class claiming ``pandid.units`` all sailed through it: the three
    shapes a stale re-export actually takes. So there is no filter here at all.
    Every name in ``__all__`` is compared, by identity, against the object the
    module it comes from holds under that name -- which is the question a reader
    is really asking when they write ``from pandid import Pump``.

    The set is checked both ways first, so a name added to ``__all__`` with no
    home, or a name silently dropped from one of the two star-imported lists,
    fails here rather than reducing the surface this file then checks.
    """
    expected = _expected_bindings()
    exported = set(pandid.__all__)

    assert exported == set(expected) | {"__version__"}, (
        "`__all__` and the modules it is assembled from disagree.\n"
        f"  in __all__ with no source module: {sorted(exported - set(expected) - {'__version__'})}\n"
        f"  in a source module and not exported: {sorted(set(expected) - exported)}"
    )

    wrong: list[str] = []
    for name, want in expected.items():
        got = getattr(pandid, name, None)
        if got is not want:
            wrong.append(f"pandid.{name} is {got!r}, not {want!r}")
    assert not wrong, "exported names bound to the wrong object:\n  " + "\n  ".join(wrong)

    version = getattr(pandid, "__version__", None)
    assert isinstance(version, str) and version, "pandid.__version__ is not a string"


# ---------------------------------------------------------------------------
# The guard's own guard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name, module", _HANDLES)
def test_a_handle_is_the_documented_class_and_stays_documented(name: str, module: str):
    """Four questions about one name, because each fails in its own way.

    A guard that only ever passes is a guard nobody has seen work, so three of
    these four are run against a mutation of the thing they check.

    1. **Exported.** The decision itself: ``connect()`` hands back a ``Stream``
       and ``fs.warnings`` is a list of ``Issue``, so both are names a reader
       annotates with and both are on the root.
    2. **Bound to the class the reference describes.** ``pandid.Port`` has to
       *be* ``pandid.ports.Port``, not merely be present -- the import
       succeeding and handing back the wrong object is #441 one step further
       along.
    3. **Still named in the documentation.** Rename ``ControlLoop`` and update
       ``__init__.py`` and this table, and every check keyed on the package's
       own class names goes quiet. This is the assertion that does not.
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
        "documentation naming a type that no longer exists."
    )

    smaller = set(pandid.__all__) - {name}
    failures = _documented_but_unreachable(lambda candidate: candidate in smaller)
    assert any(
        failure.startswith("docs/api.md:") and f"`{name}`" in failure for failure in failures
    ), f"removing {name} from __all__ went unnoticed: {failures}"


def test_the_rename_guard_can_tell_a_documented_name_from_one_that_is_not():
    """``_documented_names()`` is the rename guard's eye; here it is shown to work.

    If it answered "yes" to everything the assertion it backs would be
    decoration, so it is asked about a spelling the reference has never used --
    the one a rename of ``ControlLoop`` might plausibly introduce.
    """
    documented = _documented_names()
    assert "ControlLoop" in documented
    assert "ControlScheme" not in documented


def test_the_resolution_check_reads_the_positions_it_claims_to():
    """The reader that decides whether a documented type exists, pinned.

    Both halves are shown: a return position and a ``Type`` column are read, a
    *value* column beside them is not -- this reference has tables whose second
    cell holds ``FC``, ``A3`` and ``CWS``, and demanding those resolve would
    make the check unusable and then ignored.
    """
    sample = "\n".join(
        [
            "| Attribute | Type | Notes |",
            "|---|---|---|",
            "| `stream_table` | `StreamOptions` | how it is drawn |",
            "",
            "| Value | Effect |",
            "|---|---|",
            "| `FC` | fail closed |",
            "",
            "```text",
            "add_loop(variable: str) -> RegulatoryLoop",
            "```",
        ]
    )
    assert {name for _, name, _ in _type_positions(sample)} == {"StreamOptions", "RegulatoryLoop"}
    assert {name for _, name, _ in _prose_class_mentions(sample)} == {"StreamOptions"}


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
