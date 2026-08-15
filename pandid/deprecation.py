"""Retiring an API: one declaration, two signals.

A deprecated spelling lives for exactly one release: it works throughout
the release it is announced in and is deleted in the next -- the six
announced in 0.1.2 were gone in 0.1.3. ``CONTRIBUTING.md`` states the
rule; this module makes it cost one line to obey.

Two signals come out of one declaration:

- a standard :class:`DeprecationWarning`, for anyone whose warning
  filters show them; and
- a ``deprecated`` finding from :func:`pandid.validate.validate`,
  because Python ignores :class:`DeprecationWarning` by default outside
  ``__main__``, and ``fs.validate()`` is what an author is told to run.

They cannot drift apart: :meth:`Deprecation.warn` builds **one**
sentence and hands the same string to ``warnings.warn`` and to the
:class:`~pandid.validate.Issue` it records::

    RETIRED = Deprecation(
        what="Pump(cooled=True)",
        instead="Pump(jacket='cooling')",
        removed_in="0.2.0",
    )

    class Pump(Unit):
        def __init__(self, name, cooled=False, **kwargs):
            ...
            if cooled:
                RETIRED.warn(self, where=name)

Invented, both halves of it: an example naming a spelling the library
really has is one real retirement away from teaching the reverse of what
the library does. ``tests/test_deprecation.py`` exercises the mechanism
through this same pair, for the same reason.

A deprecation is declared as a **module constant beside the code that
honours it**, so the sentence an author reads sits next to the branch
that triggers it, and so :func:`declarations` can enumerate what this
version is retiring without anybody keeping a list.

Where the finding is kept
-------------------------

``validate()`` runs on a flowsheet after layout, while a deprecated call
happens at *construction*, often before ``fs.add()`` -- so there may be
no flowsheet in scope to record against. The finding rides on the object
the author is already holding, and :func:`findings` collects from
everything the sheet holds when ``validate()`` runs.

A carrier is the flowsheet itself, or anything it holds a list of:
units, streams, loops, components, annotations. That is the general rule
rather than a list of the classes that have a deprecation today, so the
first customer needs no edit here. A unit built and never added keeps
its finding and is never reported, which is correct: ``validate()``
answers for the drawing.

A carrier is required. A finding with nothing to ride on reaches no
sheet's ``validate()``, and the only home left for it is the process --
which is one sheet's finding read out by every *other* sheet built in
the same interpreter. Such a call still raises its
:class:`DeprecationWarning`, which is the signal that does not need a
sheet to arrive.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pandid.validate import Issue

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet

#: The code every deprecation reports under. One code for all of them:
#: the code is what a caller filters on, and "this sheet uses something
#: that is going away" is one thing to filter for. What went and what
#: replaces it is the message's job.
CODE = "deprecated"

#: The instance attribute a carrier's findings are kept in. Named only
#: here: a carrier does not declare it, and nothing outside this module
#: reads it.
_ATTR = "_deprecations"

#: The flowsheet attributes whose members can carry a finding: every
#: list a :class:`~pandid.flowsheet.Flowsheet` holds of objects an
#: author built and still has a handle on. ``streams`` is in it even
#: though a stream is minted by ``connect()``, since ``connect()``'s own
#: signature is what a deprecation there would be about.
_HELD = ("units", "streams", "loops", "components", "annotations")


@dataclass(frozen=True)
class Deprecation:
    """One retired spelling: what goes, what replaces it, and when.

    Frozen, and so hashable, so a caller can put the ones it cares about
    in a set.

    Args:
        what: The call being retired, spelled the way an author types it
            (``"Valve(variant='control')"``). Not a prose description:
            the author has to find this string in their own file.
        instead: The call that replaces it, spelled the same way.
            Required, and required to be a *call*, so the finding ends
            on the line the author types next.
        removed_in: The release the old spelling stops working in.
            Always the release after the one it is announced in.
    """

    what: str
    instead: str
    removed_in: str

    def __post_init__(self) -> None:
        for field, value in (("what", self.what), ("instead", self.instead),
                             ("removed_in", self.removed_in)):
            if not str(value).strip():
                raise ValueError(
                    f"a Deprecation needs a {field}: the finding names the call that "
                    f"is going, the call that replaces it and the release it goes in, "
                    f"and one of the three left empty is a finding nobody can act on"
                )

    def message(self, where: str = "") -> str:
        """The one sentence both signals carry.

        *where* is the thing on the sheet that has to be edited -- a
        unit tag, a stream name -- and is left out when the call named
        nothing in particular. It goes in front, as every other finding
        in :mod:`pandid.validate` puts it. The replacement comes last,
        so the sentence ends on the line the author types next.
        """
        lead = f"{where}: " if where else ""
        return (f"{lead}{self.what} is deprecated and is removed in pandid "
                f"{self.removed_in}; use {self.instead}")

    def warn(self, carrier: object, *, where: str = "",
             stacklevel: int = 3) -> None:
        """Emit both signals for one deprecated call.

        The sentence is built once and used twice: the
        ``DeprecationWarning`` a filter shows and the finding
        ``validate()`` reports are the same ``str`` object.

        *carrier* is the object the finding rides on until
        ``validate()`` runs: the unit under construction, the stream,
        the flowsheet. Required, and required to be able to hold the
        finding, so that a call with nothing to attach to fails here
        rather than quietly reporting against sheets it has no
        connection to.

        *stacklevel* defaults to 3 so the warning points at the author's
        line: 1 is this method, 2 is the library function that called
        it, 3 is where that function was called from. A helper that adds
        a frame between the two passes 4.

        Recorded once per distinct sentence per carrier, since a
        constructor that triggers the same deprecation twice has given
        the author one thing to fix. The ``DeprecationWarning`` is still
        emitted each time; suppressing a repeat is what the ``warnings``
        module's own filters are for.
        """
        if not hasattr(carrier, "__dict__"):
            raise TypeError(
                f"a deprecation rides to validate() on a carrier -- the unit under "
                f"construction, the stream, the flowsheet -- and {carrier!r} cannot "
                f"hold one"
            )
        text = self.message(where)
        warnings.warn(text, DeprecationWarning, stacklevel=stacklevel)
        bucket = vars(carrier).setdefault(_ATTR, [])
        if not any(seen.message == text for seen in bucket):
            bucket.append(Issue("warning", CODE, text))


def _recorded(obj: object) -> list[Issue]:
    """The findings sitting on one carrier.

    Through ``__dict__`` rather than ``getattr``, so a class attribute
    sharing the name cannot be found instead and
    :meth:`pandid.units.Unit.__getattr__` -- which turns an unknown name
    into a message about the unit's ports -- is never entered.
    """
    return list(getattr(obj, "__dict__", {}).get(_ATTR, ()))


def findings(fs: "Flowsheet") -> list[Issue]:
    """Every deprecation this sheet triggered, and no other sheet's.

    Called by :func:`pandid.validate.validate`, which reports rather
    than recomputes: the findings were built at the deprecated call, the
    only moment that knows one was made.
    """
    out = _recorded(fs)
    for held in _HELD:
        for obj in getattr(fs, held, ()):
            out.extend(_recorded(obj))
    return out


def declarations() -> dict[str, Deprecation]:
    """Every deprecation this version declares, keyed by where.

    Imports each of pandid's own modules and collects the module-level
    :class:`Deprecation` constants in them, which is why the convention
    is a module constant rather than one built inline at the call: a
    declaration nothing can enumerate outlives its release quietly.
    ``tests/test_deprecation.py`` enumerates them and holds each to a
    ``removed_in`` that has not shipped yet.

    A constant imported into a second module appears under both names.
    """
    import importlib
    import pkgutil

    import pandid

    found: dict[str, Deprecation] = {}
    for info in pkgutil.walk_packages(pandid.__path__, prefix="pandid."):
        module = importlib.import_module(info.name)
        for name, value in vars(module).items():
            if isinstance(value, Deprecation):
                found[f"{info.name}.{name}"] = value
    return found
