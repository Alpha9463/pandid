"""The documentation may not name a type the package root does not export.

``docs/api.md`` named ``ControlLoop`` as a return type three times and neither it
nor ``Loop`` nor ``ValveStation`` was importable from ``pandid`` (#441). A reader
who followed the reference exactly wrote ``from pandid import ControlLoop`` and
got an ``ImportError``: the documentation described an API the package did not
have. That is worse here than it looks, because this package ships ``py.typed``
and asks to be annotated against, and because #174 makes "correct on the first
try, from the documentation alone" a goal rather than a nicety.

The rule this file holds the package and its documentation to::

    A type the documentation names **bare** is importable from ``pandid``.
    A type that is not is named with the module it lives in.

So ``Stream``, ``Port``, ``Loop`` and ``Issue`` are on the package, and
``pandid.state.State``, ``pandid.document.StreamTableOptions`` and
``pandid.render.symbols.Symbol`` -- three the package deliberately does not
export -- are written out in full wherever the reference mentions them. Either
spelling imports. Nothing here cares which of the two an author picks; every
check fails on the third possibility, which is the bug.


How this file is built, and why it is built that way
----------------------------------------------------

Three rounds of review found ten defects in this guard and every one of them was
the same mistake: **the guard accepted a claim it had not resolved.** It skipped
a value whose type it did not like; it took a ``.get()`` returning ``None`` as
permission to move on; it read a dotted path's *shape* and called that a module.
The last of those was the sharpest, because a documentation path that looks
right and does not import is #441's own user-visible failure, waved through by
the guard written to stop it.

So there is one rule about the checking, and it is stronger than the rule being
checked::

    A name the documentation states is resolved to a real object, or this file
    fails. There is no third outcome.

Everything below follows from that, and the three mechanisms that make it hold
are worth naming, because a future edit that weakens any of them puts the holes
back:

1. **Resolution, never pattern-matching.** ``_resolves_by_stated_path()`` looks
   the module up in a table of modules that have actually been imported and asks
   it for the attribute. It cannot accept ``pandid.StreamTableOptions``, because
   there is no such module and ``pandid`` has no such attribute -- where a regex
   over the path's shape accepted it happily.
2. **One list of reading sites.** Every place a name can be stated -- Markdown
   prose, ``Type`` columns, signature blocks, return annotations, docstrings --
   is read into one list of :class:`Mention`, and every check iterates that list.
   A reading site fixed for one check is fixed for all of them, which is what
   was not true when the resolution rule reached the three Markdown files and
   not the docstrings beside them.
3. **Derived sets, never written ones.** The modules that must be reachable come
   off the filesystem; the expected binding of 129 of the 142 exports comes from
   ``units.__all__`` and ``devices.__all__``. A hand-kept list cannot know about
   the module or the class added tomorrow, which is the same objection #484
   makes to a hand-kept field list.

The one thing this file does *not* demand is that every capitalised token in
English prose resolve. It cannot: ``CV-305``, ``A1A``, ``CWSH`` and ``NTS`` are
spelled like one-word class names and are tags, specs, services and scales.
:attr:`Mention.must_resolve` marks the places where the reading is certain, and
those are the places the rule is enforced. Which places those are is pinned by
the fixture tests at the bottom, so widening or narrowing it is a deliberate act
with a diff.

``CONTRIBUTING.md`` is deliberately not read. It documents the internals to
someone changing them -- ``OverlayPart``, ``Deprecation``, ``IsoPart`` -- and an
internal named there describes machinery rather than promising a surface.
"""

from __future__ import annotations

import ast
import builtins
import importlib
import inspect
import pkgutil
import re
from functools import cache
from pathlib import Path
from types import ModuleType
from typing import Callable, NamedTuple, TypeGuard

import pytest

import pandid

_REPO = Path(__file__).resolve().parent.parent
_PACKAGE = Path(pandid.__file__).resolve().parent

#: What a user reads and writes imports from. Every one is shipped in the sdist.
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

#: A dotted path under this package, as the text writes it. Resolving it is a
#: separate job and a real one -- this only finds the candidate.
_DOTTED = re.compile(r"\bpandid(?:\.\w+)+\b")

#: A Markdown table's cell separator. ``\|`` is Markdown's escape for a literal
#: pipe and is how this reference writes a union inside a cell -- ``Route \|
#: None``. Splitting on a bare ``|`` cut those cells in half and lost the type
#: in them, so the escaped form is excluded here and unescaped after the split.
_CELL_SEPARATOR = re.compile(r"(?<!\\)\|")

#: A Sphinx cross-reference whose target *is a type*: ``:class:`` and ``:exc:``.
#: The member roles are deliberately not here. ``:meth:`` and ``:attr:`` name a
#: member, so their last component is a method or an attribute -- reading
#: ``:attr:`COMPOSITION``` as a type name asks a class-level dict to be a class.
#: The class in a member role's path is a *prefix* of it, which
#: :func:`_resolves_by_stated_path` already follows when one is needed.
_SPHINX_TYPE_ROLE = re.compile(r":(?:class|exc):`~?([\w.]+)`")

#: Any Sphinx cross-reference, type or member. Only used to confirm the split
#: above is real in the fixture test.
_SPHINX_ROLE = re.compile(r":(?:class|meth|attr|func|obj|exc):`~?([\w.]+)`")

#: Types from outside this package that the **Markdown** names, each with the
#: module it really comes from -- because "resolved" here means imported and
#: looked up, for these as much as for anything else. Three names is the whole
#: of the escape hatch on that side, and a fourth belongs here only when the
#: reference genuinely hands a reader a type from outside.
#:
#: The source side needs no such list. A name written in a docstring or an
#: annotation is resolved against *the namespace of the module it was written
#: in* -- ``Any`` in ``pandid/units.py`` is ``pandid.units.Any``, which is
#: ``typing.Any``, because that file imported it. That is the same resolution
#: Python itself would do, so it costs nothing to be exactly right, and a list
#: is only needed where there is no module to ask.
_FOREIGN_TYPES = {"Path": "pathlib", "Callable": "typing", "Protocol": "typing"}


class Mention(NamedTuple):
    """One place a name is stated, and everything needed to judge it.

    ``context`` is the text a qualification may be written in -- the Markdown
    line, or a member's return annotation and docstring together. It is what
    :func:`_resolves_by_stated_path` reads, so it must be the whole of what a
    reader has in front of them at that point.

    ``must_resolve`` says the reading is certain: the text is naming a type
    here, so a name that resolves to nothing is a defect rather than an English
    word that happens to be capitalised.

    ``home`` is the module the text was written in, for text that has one. It is
    the namespace a name in that text would be resolved in by Python, so it is
    the namespace it is resolved in here. Markdown has no home, which is why the
    three foreign types it names are listed instead.
    """

    where: str
    name: str
    context: str
    must_resolve: bool
    home: str | None = None


# ---------------------------------------------------------------------------
# What the package contains
# ---------------------------------------------------------------------------


def _modules_on_disk() -> set[str]:
    """Every importable module under ``pandid/``, read off the filesystem.

    The filesystem is the authority a hand-written list cannot be. A module
    added tomorrow is in this set the moment it is saved, which is the property
    the list this replaced did not have: that list passed happily while the walk
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
            # enumerates *within* rather than yielding. It is already imported,
            # and _modules() adds it under its own name.
            continue
        names.add("pandid." + ".".join(parts))
    return names


@cache
def _modules() -> dict[str, ModuleType]:
    """Every module of this package, imported, keyed by name.

    This table is what makes resolution possible rather than approximate. A
    dotted path in the documentation is a module of this package or it is not,
    and asking this dict is how that question gets an answer -- no ``try:
    import_module`` whose ``except ImportError`` would answer "not a module" for
    a module that exists and is broken.

    **Nothing is caught while building it.** An import that failed used to be
    skipped, and a skipped module is a module whose classes every check then
    stops asking about -- so a broken ``pandid.render`` made a bare ``Symbol``
    in the documentation pass. No module here needs an optional extra to import
    (the ``pdf`` extra is imported inside the function that rasterises, not at
    module scope), so an ``ImportError`` is a broken package and has to be
    heard. Should one ever need an extra, catch *that module by name*.

    Letting the error out covers the module that raises. It does not cover a
    walk that quietly enumerates fewer modules than exist, which would satisfy
    every check in this file, so the two sets are compared. Both directions:
    on disk and not walked is the blind spot, walked and not on disk means this
    file's own derivation has drifted from ``pkgutil``'s.
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
    imported["pandid"] = pandid
    return imported


@cache
def _public_classes() -> dict[str, str]:
    """Every public class this package defines **at run time**, and its module.

    Keyed by bare name because that is how the documentation writes it, and
    valued by ``__module__`` rather than by where it was imported, so a class
    re-exported into three namespaces is still one entry answering "where does
    this actually live".

    Run time is the point: this is the set the export rule can apply to, because
    only a class that exists when Python runs can be imported from ``pandid``.
    The ``TYPE_CHECKING``-only narrowing classes are deliberately not here; see
    :func:`_type_checking_classes`.
    """
    found: dict[str, str] = {}
    for name, module in _modules().items():
        if name == "pandid":
            continue
        for attribute, value in vars(module).items():
            if attribute.startswith("_") or not inspect.isclass(value):
                continue
            if getattr(value, "__module__", "").startswith("pandid."):
                found[attribute] = value.__module__
    return found


@cache
def _type_checking_classes() -> dict[str, str]:
    """Public classes declared only under ``if TYPE_CHECKING:``, and their module.

    A third of the narrowing classes the reference names do not exist at run
    time: ``Absorber2``, ``Column2`` and ``ColumnDraw1`` .. ``ColumnDraw8`` are
    declared inside ``if TYPE_CHECKING:`` in ``pandid/units.py``, so a type
    checker can resolve ``Column("T-1", n_feeds=2).feed_2``. They are real names
    the reference is right to use and no runtime sweep can ever see one.

    So they are resolved statically, against the source that declares them --
    which is a resolution and not a guess, because ``ast`` is the same parser
    Python uses. Resolving them dynamically is not merely inconvenient, it is
    impossible: the whole point of the declaration is that it is not executed.

    The exemption is proved rather than asserted. Each of these is checked to be
    genuinely absent from its module at run time, so "exempt from the export
    rule because it cannot be imported" is a fact about the package rather than
    a claim about it -- and a class that moved out of a ``TYPE_CHECKING`` block
    stops being exempt on the next run.
    """
    found: dict[str, str] = {}
    for module_name, module in _modules().items():
        if module_name == "pandid":
            continue
        source = Path(str(module.__file__)).read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(module.__file__))
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            test = node.test
            guard = test.attr if isinstance(test, ast.Attribute) else getattr(test, "id", "")
            if guard != "TYPE_CHECKING":
                continue
            for inner in ast.walk(node):
                if isinstance(inner, ast.ClassDef) and not inner.name.startswith("_"):
                    found[inner.name] = module_name

    still_present = {
        name: module for name, module in found.items() if hasattr(_modules()[module], name)
    }
    assert not still_present, (
        "these are declared under `if TYPE_CHECKING:` and exist at run time "
        "anyway, so the reason they are exempt from the export rule -- that "
        f"nobody can import them -- is not true of them: {still_present}"
    )
    return found


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
    words about the builtin. It is a value, not a statement about a type.
    """
    if isinstance(member, (classmethod, staticmethod)):
        return member.__func__
    if isinstance(member, property):
        return member.fget
    if inspect.isfunction(member):
        return member
    return None


def _authored_doc(fn: object) -> str:
    """``fn``'s docstring, unless the docstring is the field list again.

    A ``@dataclass`` with no docstring of its own is given one by the decorator:
    the constructor signature, field annotations and all. Those annotations are
    read as storage rather than as a promise (see
    :func:`_public_surface_mentions`), so letting them back in through the
    generated docstring would be answering a question this file has decided not
    to ask.
    """
    doc = inspect.getdoc(fn) or ""
    if inspect.isclass(fn) and doc.startswith(fn.__name__ + "("):
        return ""
    return doc


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def _is_class_named(value: object, name: str) -> TypeGuard[type]:
    """Is ``value`` a class of this package's, under exactly this name?

    Both halves matter. Without the name check, ``getattr(module, name)``
    landing on a re-exported alias of something else would satisfy the caller;
    without the module check, a stdlib class re-exported into a pandid module
    would.
    """
    return (
        inspect.isclass(value)
        and value.__name__ == name
        and getattr(value, "__module__", "").startswith("pandid")
    )


def _resolves_at_root(name: str) -> bool:
    """Can a reader write ``from pandid import <name>`` and get the class?

    Asked of the package object rather than of ``__all__``, because ``__all__``
    is a list of strings and a list of strings is a claim, not a binding.
    """
    return _is_class_named(getattr(pandid, name, None), name)


def _resolves_by_stated_path(context: str, name: str) -> str | None:
    """The module this text states ``name`` lives in, if the statement is true.

    This is the function three rounds of review kept coming back to, and the
    reason is worth writing down. It used to match the *shape* of a dotted path
    -- ``pandid`` something ``.Name`` -- and treat a match as a statement of
    where the class lives. So ``pandid.StreamTableOptions`` passed: it has the
    shape, there is no such module, ``pandid`` has no such attribute, and the
    reference was handing readers an import that raises. That is #441's own
    failure, reproduced inside the guard built to prevent it.

    It now resolves. Every dotted path in the text is cut at each of its
    boundaries, each prefix is looked up in the table of modules that have
    actually been imported, and the module is asked for the attribute. A path is
    a statement of where the class lives only when following it arrives at the
    class. ``pandid.render.symbols.SymbolRegistry.for_unit`` names
    ``pandid.render.symbols``, which really does hold ``Symbol``;
    ``pandid.StreamTableOptions`` names nothing at all.
    """
    modules = _modules()
    for path in _DOTTED.findall(context):
        parts = path.split(".")
        for stop in range(1, len(parts) + 1):
            stated = ".".join(parts[:stop])
            module = modules.get(stated)
            if module is None:
                continue
            value = getattr(module, name, None)
            # The stated module must be where the class *lives*, not merely a
            # module that imported it. `pandid/spec.py` does `from
            # pandid.document import StreamTableOptions` for its own use, so
            # `pandid.spec.StreamTableOptions` is a real attribute and a working
            # import -- and telling a reader the class lives there is still
            # wrong. It also let a docstring returning an unexported type pass
            # by naming some unrelated module of this package in the same
            # breath, which is how `Flowsheet.from_dict` got away with it.
            if _is_class_named(value, name) and value.__module__ == stated:
                return stated
    return None


def _resolves_elsewhere(name: str, home: str | None) -> bool:
    """Does this name resolve to something that is not this package's to export?

    Three ways, and every one of them is a lookup rather than a list membership:

    * a builtin -- how ``ValueError`` and ``KeyError`` are named;
    * a name bound in ``home``, the module the text was written in. ``Any`` in a
      ``pandid/units.py`` docstring is ``pandid.units.Any`` is ``typing.Any``,
      because that file imported it, and asking the module is the same
      resolution Python would do;
    * one of the three foreign types the Markdown names, whose module is
      imported and asked. Markdown has no ``home`` to ask, which is the only
      reason that list exists.
    """
    if hasattr(builtins, name):
        return True
    if home is not None:
        module = _modules().get(home)
        if module is not None and hasattr(module, name):
            return True
    module_name = _FOREIGN_TYPES.get(name)
    return module_name is not None and hasattr(importlib.import_module(module_name), name)


# ---------------------------------------------------------------------------
# Where names are stated -- one list, read by every check
# ---------------------------------------------------------------------------


def _table_cells(line: str) -> list[str]:
    """A Markdown table row's cells, with ``\\|`` respected and then unescaped."""
    parts = _CELL_SEPARATOR.split(line.strip())
    if parts and not parts[0].strip():
        parts = parts[1:]
    if parts and not parts[-1].strip():
        parts = parts[:-1]
    return [part.strip().replace("\\|", "|") for part in parts]


def _markdown_mentions(relative: str) -> list[Mention]:
    """Every name a user-facing document states, and how certainly it states it.

    Four readings, and the certainty differs between them:

    * a **backticked span** in prose. Every name in it is a candidate for the
      export rule; only a two-word CamelCase name is required to *resolve*,
      because ``CWSH`` and ``A1A`` are spelled like one-word class names.
    * a **``Type`` column** -- a cell in a column whose header is literally
      ``Type``. Found by heading and not by position, which is what keeps the
      *value* columns out: this reference has tables whose second cell holds
      ``FC``/``FO``, ``A4``/``A3`` and ``P``/``FB``/``CWS``. Certain.
    * a **return position** in a ``text`` fence -- ``-> ControlLoop``, the shape
      #441 had. Certain.
    * **every other line of a ``text`` fence**, which is where the signature
      blocks are. Not certain: those fences also carry sample error messages and
      sample stdout, and the reference's own placeholders (``MyEngine``,
      ``MyRouter``) live there, which a reader is invited to replace with a
      class of their own that this package will never have.

    A ``python`` fence is not read at all. It is a runnable example, so it
    carries its own import line -- which
    ``test_every_import_the_documentation_writes_is_an_import_that_works``
    executes, so that is an argument backed by a check rather than a hope -- and
    its string literals are prose: ``units.Block("Synthesis Loop")`` is not a
    mention of ``Loop``. Unfenced text outside backticks is not read for the
    mirror-image reason: "the Port table" is English.
    """
    mentions: list[Mention] = []
    language: str | None = None
    type_column: int | None = None
    for number, line in enumerate((_REPO / relative).read_text(encoding="utf-8").splitlines(), 1):
        where = f"{relative}:{number}"
        opening = _FENCE.match(line)
        if opening is not None and language is None:
            language = opening.group(1) or "plain"
            continue
        if language is not None and line.strip() == "```":
            language = None
            continue

        if language == "text":
            for name in _CLASS_NAME.findall(line):
                mentions.append(Mention(where, name, line, must_resolve=False))
            for returns in re.findall(r"->\s*([^#\n]+)", line):
                for name in _CLASS_NAME.findall(returns):
                    mentions.append(Mention(where, name, line, must_resolve=True))
            continue
        if language is not None:
            continue

        for span in _BACKTICKED.findall(line):
            for name in _CLASS_NAME.findall(span):
                mentions.append(Mention(where, name, line, must_resolve=False))
            for name in _MULTIWORD_NAME.findall(span):
                mentions.append(Mention(where, name, line, must_resolve=True))

        if not line.lstrip().startswith("|"):
            type_column = None
            continue
        cells = _table_cells(line)
        if "Type" in cells:
            type_column = cells.index("Type")
            continue
        if type_column is not None and type_column < len(cells):
            for span in _BACKTICKED.findall(cells[type_column]):
                for name in _CLASS_NAME.findall(span):
                    mentions.append(Mention(where, name, line, must_resolve=True))
    return mentions


def _public_surface_mentions() -> list[Mention]:
    """Every name the public surface states, in the two places a caller is told.

    A documented type gets into ``docs/api.md`` because a signature grew it
    first: #441 is three names that arrived as ``-> ControlLoop``, ``-> Loop``
    and ``-> ValveStation`` and were written up from there. So the source side
    is read by the same rules and into the same list -- the fix that made a
    nonexistent name in Markdown a failure was worthless while the docstring
    beside it still swallowed one.

    * **Return annotations.** What a public method hands back. Certain.
    * **Docstrings**: two-word CamelCase names, and the target of every Sphinx
      cross-reference. Certain, and measurably so -- the public surface states
      no two-word CamelCase name today that is not a class of this package's or
      a builtin, so the rule costs nothing and catches the stale reference.

    Parameter and field annotations are read as neither. ``Port.state`` is
    annotated ``State | None`` against ``pandid/ports.py``'s own import: that
    describes storage rather than promising a caller a type, and the reference
    already writes that one out in full as ``pandid.state.State``. What such an
    annotation must do is *resolve*, and ``mypy pandid`` is the gate that owns
    it.
    """
    mentions: list[Mention] = []

    def read(owner: str, fn: object) -> None:
        returns = str((getattr(fn, "__annotations__", None) or {}).get("return", ""))
        doc = _authored_doc(fn)
        context = returns + " " + doc
        home = getattr(fn, "__module__", None)
        for name in _CLASS_NAME.findall(returns):
            mentions.append(Mention(owner, name, context, True, home))
        for name in _MULTIWORD_NAME.findall(doc):
            mentions.append(Mention(owner, name, context, True, home))
        for target in _SPHINX_TYPE_ROLE.findall(doc):
            # The class in the path is its last capitalised component, not its
            # last component: this project writes `:class:`Block.ports_on`` for
            # a member of a class as well as `:class:`~pandid.streams.Stream``
            # for the class itself, and in the first the class named is `Block`.
            # Taking the leaf regardless asked `ports_on` to be a type.
            capitalised = [part for part in target.split(".") if part[:1].isupper()]
            if capitalised:
                mentions.append(Mention(owner, capitalised[-1], context, True, home))

    for exported_name in pandid.__all__:
        value = getattr(pandid, exported_name)
        if inspect.isfunction(value):
            read(f"pandid.{exported_name}", value)
        if not inspect.isclass(value):
            # A module (`units`, `devices`) or `__version__`: no return type and
            # no docstring of this project's own. That each is the *right*
            # object rather than merely present is
            # test_every_exported_name_is_bound_to_the_object_it_names, which
            # has no filter at all.
            continue
        read(exported_name, value)
        for member_name, member in _public_members(value).items():
            fn = _documentation_bearing(member)
            if fn is not None:
                read(f"{exported_name}.{member_name}", fn)
    return mentions


@cache
def _all_mentions() -> tuple[Mention, ...]:
    """Every place this project states a type name. One list; every check reads it."""
    mentions: list[Mention] = []
    for relative in _USER_DOCS:
        mentions.extend(_markdown_mentions(relative))
    mentions.extend(_public_surface_mentions())
    return tuple(mentions)


# ---------------------------------------------------------------------------
# The verdicts
# ---------------------------------------------------------------------------


def _unreachable(exported: Callable[[str], bool]) -> list[str]:
    """Names stated bare that ``exported`` says the root does not carry.

    Takes the export test as an argument so the mutation tests below can hand it
    a smaller ``__all__`` and prove this actually fails.

    The order of the questions is the order a reader meets them. Is it on the
    package? Then the bare spelling works. Does the text state a path that
    really resolves? Then the qualified spelling works. Is it a builtin, a
    foreign type or a name that exists only for a type checker? Then this rule
    has no purchase on it -- none of the three can be exported from ``pandid``,
    and the first two are not this package's to export. Otherwise it is a class
    of ours, stated in a way that does not import, and that is the defect.
    """
    failures: list[str] = []
    for mention in _all_mentions():
        module = _public_classes().get(mention.name)
        if module is None:
            # Not a class this package defines at run time, so there is nothing
            # here that *could* be exported: a builtin, a foreign type, a name
            # that exists only for a type checker, an English word, a tag, or a
            # reader's own placeholder -- or a name that resolves to nothing,
            # which _unresolved() reports from this same list, so it is not lost.
            continue
        if exported(mention.name) and _resolves_at_root(mention.name):
            continue
        if _resolves_by_stated_path(mention.context, mention.name) is not None:
            continue
        # `home` is deliberately not consulted. That `pandid/flowsheet.py`
        # imports `StreamTableOptions` for its own use answers the question
        # "does this name exist"; it says nothing whatever about whether a
        # *reader* can reach it, which is the question here. Letting it in was a
        # silent pass on a docstring returning an unexported type.
        failures.append(
            f"{mention.where}: `{mention.name}` ({module}) -- {mention.context.strip()}"
        )
    return failures


def _unresolved() -> list[str]:
    """Names stated where the reading is certain, that resolve to nothing at all.

    The likeliest real defect in a reference this size is not a missing export;
    it is a rename that reached the code and half the mentions. Every check keyed
    on the package's own class names is blind to it by construction -- ``|
    stream_table | StreamOptions |`` and ``-> RegulatoryLoop`` read as perfectly
    clean, because no class of either name exists to be found unexported. This
    is the check that starts from the text instead.
    """
    failures: list[str] = []
    for mention in _all_mentions():
        if not mention.must_resolve:
            continue
        if mention.name in _public_classes() or mention.name in _type_checking_classes():
            continue
        if _resolves_elsewhere(mention.name, mention.home):
            continue
        failures.append(f"{mention.where}: `{mention.name}` -- {mention.context.strip()[:120]}")
    return failures


# ---------------------------------------------------------------------------
# The rule
# ---------------------------------------------------------------------------


def test_every_type_the_documentation_names_is_importable_from_the_root():
    """The guard #441 asks for: fix it once and it stays fixed.

    Both halves of the rule are honoured, so a name may be added either way.
    Exporting it is right when a reader holds the object -- ``connect()`` hands
    back a :class:`~pandid.streams.Stream`, ``validate()`` a list of
    :class:`~pandid.validate.Issue`. Writing the module out is right when the
    class is machinery the reader never types: nothing constructs a
    :class:`~pandid.document.StreamTableOptions` (every flowsheet has one) and
    nothing builds a second symbol registry.
    """
    failures = _unreachable(lambda name: name in pandid.__all__)
    assert not failures, (
        "the documentation names types that `import pandid` cannot reach.\n"
        "Either export the name from pandid/__init__.py, or state the module it "
        "lives in at the mention -- a module that really holds it:\n  " + "\n  ".join(failures)
    )


def test_every_type_the_documentation_names_resolves_to_something():
    """A documented type has to exist. Markdown and docstrings alike."""
    failures = _unresolved()
    assert not failures, (
        "the documentation names types that do not exist. A rename that reached "
        "the code and not the reference looks exactly like this:\n  " + "\n  ".join(failures)
    )


def test_every_import_the_documentation_writes_is_an_import_that_works():
    """An example's own ``from pandid...`` line has to run.

    ``python`` fences are not read for type names because an example carries its
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
    all satisfied it. Identity that *declined to look* at non-classes was the
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
    4. **Removal is caught.** The reachability check, run against an ``__all__``
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
    failures = _unreachable(lambda candidate: candidate in smaller)
    assert any(
        failure.startswith("docs/api.md:") and f"`{name}`" in failure for failure in failures
    ), f"removing {name} from __all__ went unnoticed: {failures}"


def _documented_names() -> set[str]:
    """Every name the three user-facing documents state, package membership aside.

    Deliberately not filtered against what ``pandid`` currently defines, which is
    what makes it the rename guard's eye: a class the package no longer has is a
    question every other check is built not to ask.
    """
    return {m.name for m in _all_mentions() if m.where.split(":")[0] in _USER_DOCS}


# ---------------------------------------------------------------------------
# The readers, pinned
# ---------------------------------------------------------------------------


def test_the_rename_guard_can_tell_a_documented_name_from_one_that_is_not():
    """``_documented_names()`` is the rename guard's eye; here it is shown to work."""
    documented = _documented_names()
    assert "ControlLoop" in documented
    assert "ControlScheme" not in documented


def test_a_stated_path_is_followed_rather_than_pattern_matched():
    """The fix at the root of round three, pinned against its own regression.

    ``pandid.StreamTableOptions`` has the shape of a path to that class and is
    not one: no such module, no such attribute on the package. Accepting it is
    handing a reader an import that raises, which is #441 exactly.
    """
    real = "see `pandid.document.StreamTableOptions` for the fields"
    assert _resolves_by_stated_path(real, "StreamTableOptions") == "pandid.document"

    wrong = "see `pandid.StreamTableOptions` for the fields"
    assert _resolves_by_stated_path(wrong, "StreamTableOptions") is None

    # A path that runs *past* the module still names it; one that stops short
    # does not, because a reader given `pandid.render` cannot write the import.
    through = ":meth:`~pandid.render.symbols.SymbolRegistry.for_unit`"
    assert _resolves_by_stated_path(through, "Symbol") == "pandid.render.symbols"
    assert _resolves_by_stated_path("`pandid.render` holds it", "Symbol") is None

    # And the module has to be where the class *lives*. `pandid.spec` imports
    # `StreamTableOptions` for its own use, so the attribute is really there and
    # the import would really work -- and it is still not where the class is,
    # so it does not place it. Accepting it let an unrelated module named
    # anywhere in the same docstring vouch for any class of this package's.
    importer = "see :mod:`pandid.spec` for the format"
    assert hasattr(importlib.import_module("pandid.spec"), "StreamTableOptions")
    assert _resolves_by_stated_path(importer, "StreamTableOptions") is None


def test_the_table_reader_survives_markdowns_escaped_pipe():
    """``Route \\| None`` is one cell, and the type in it has to be read.

    Splitting on a bare ``|`` cut this cell in half and dropped the type, so a
    ``Type`` column stating a union -- which is most of the interesting ones,
    ``TitleBlock \\| None`` and ``Route \\| None`` among them -- went unchecked.
    """
    row = r"| `route` | `Route \| None` | resolved waypoints |"
    assert _table_cells(row) == ["`route`", "`Route | None`", "resolved waypoints"]

    sample = "\n".join(
        [
            "| Member | Type | Notes |",
            "|---|---|---|",
            row,
        ]
    )
    (_REPO / "docs/_fixture.md").write_text(sample, encoding="utf-8")
    try:
        read = {m.name for m in _markdown_mentions("docs/_fixture.md") if m.must_resolve}
    finally:
        (_REPO / "docs/_fixture.md").unlink()
    assert read == {"Route", "None"}


def test_the_readers_read_the_positions_they_claim_to_and_no_others():
    """What is read, and what is deliberately not. Widening this needs a diff.

    A ``Type`` column is read and the *value* column beside it is not; a return
    position is read and the placeholder a reader is invited to replace is not.
    Demanding ``FC``, ``A3`` and ``MyEngine`` resolve would make the check
    unusable, and an unusable check gets deleted rather than fixed.
    """
    sample = "\n".join(
        [
            "The Port table lists them.",
            "`connect()` returns a `Stream`, a `RegulatoryLoop` and a `CV-305` tag.",
            "",
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
            "fs.layout(engine=MyEngine())",
            "```",
            "```python",
            'fs.add(units.Block("Synthesis Loop"))',
            "```",
        ]
    )
    (_REPO / "docs/_fixture.md").write_text(sample, encoding="utf-8")
    try:
        mentions = _markdown_mentions("docs/_fixture.md")
    finally:
        (_REPO / "docs/_fixture.md").unlink()

    must = {m.name for m in mentions if m.must_resolve}
    seen = {m.name for m in mentions}
    assert must == {"RegulatoryLoop", "StreamOptions"}
    # Read, and required to resolve where the reading is certain. `Stream` is
    # read from prose and *not* required to, which is the one-word limit stated
    # at the top of this file: nothing separates `Stream` from `CWSH`. It is
    # still held to the export rule, and it is required to resolve wherever the
    # text actually names a type -- the Type column and the return position
    # above, which is why both of those are in `must`.
    assert "Stream" in seen and "CV" in seen
    # Read but never required to resolve: a reader's own placeholder, and the
    # value column's codes. Never read at all: English prose, and python fences.
    assert "MyEngine" in seen and "FC" in seen
    assert "Port" not in seen and "Synthesis" not in seen and "Loop" not in seen


def test_the_public_surface_reader_reads_returns_docstrings_and_roles():
    """The three readings on the source side, each shown to be taken.

    The docstring reading is the one round three found missing: the resolution
    rule reached the three Markdown files and stopped there, so a nonexistent
    type named in a public docstring was discarded by a ``.get()`` that returned
    ``None``.
    """

    from pandid import ControlLoop, Stream

    class Sample:
        """A sample. Mentions a `RegulatoryLoop` and :class:`~pandid.loops.Loop`."""

        # `from __future__ import annotations` is on, so these reach
        # `__annotations__` as the strings this file reads them as -- while
        # still being real names a type checker resolves, which is why they are
        # imported rather than quoted.
        def method(self) -> Stream:
            """Hands back a StreamTableOptions."""
            raise NotImplementedError  # never called: only the signature is read

        @classmethod
        def build(cls) -> ControlLoop:
            """The constructor an engineer reaches for."""
            raise NotImplementedError  # never called: only the signature is read

    read = {
        name
        for name, member in vars(Sample).items()
        if _documentation_bearing(member) is not None
        for name in [name]
    }
    assert {"method", "build"} <= read, "a classmethod is documentation-bearing"

    mentions: list[Mention] = []
    for member_name, member in vars(Sample).items():
        fn = _documentation_bearing(member)
        if fn is None:
            continue
        returns = str((getattr(fn, "__annotations__", None) or {}).get("return", ""))
        doc = _authored_doc(fn)
        for name in _CLASS_NAME.findall(returns):
            mentions.append(Mention(member_name, name, returns, must_resolve=True))
        for name in _MULTIWORD_NAME.findall(doc):
            mentions.append(Mention(member_name, name, doc, must_resolve=True))
    names = {m.name for m in mentions}
    assert {"Stream", "ControlLoop", "StreamTableOptions"} <= names, (
        "the return annotation of a method and of a classmethod, and a two-word "
        f"name in a docstring, all have to be read: {sorted(names)}"
    )

    doc = inspect.getdoc(Sample) or ""
    assert [t.rsplit(".", 1)[-1] for t in _SPHINX_ROLE.findall(doc)] == ["Loop"]
    assert "RegulatoryLoop" in _MULTIWORD_NAME.findall(doc)
