"""Retiring an API: one declaration, two signals.

A deprecated spelling lives for exactly one release. It still works throughout
the release it is announced in and is deleted in the next one -- deprecated in
0.1.2, gone in 0.1.3. Longer than that is a second API kept alive beside the
first, and this package would rather fix the design than carry a wrong shape for
compatibility. ``CONTRIBUTING.md`` states the rule; this module is what makes it
cost one line to obey.

Two signals come out of one declaration:

- a standard :class:`DeprecationWarning`, for anyone whose warning filters show
  them; and
- a ``deprecated`` finding from :func:`pandid.validate.validate`, because
  ``fs.validate()`` is what an author is told to run and what an agent is told
  to check, while Python ignores :class:`DeprecationWarning` by default outside
  ``__main__``. A warning nobody's filter shows is not a signal.

The two cannot drift apart, and that is why this is a module rather than a
convention: :meth:`Deprecation.warn` builds **one** sentence and hands the same
string to ``warnings.warn`` and to the :class:`~pandid.validate.Issue` it
records. It is the reasoning :attr:`pandid.units.Block._faces` is written down
with -- a fact recorded in two places is a fact that will one day disagree with
itself -- applied to a fact that is read by two audiences instead of two
subsystems::

    RETIRED = Deprecation(
        what="Valve(variant='control')",
        instead="Valve(variant='globe')",
        removed_in="0.1.3",
    )

    class Valve(Unit):
        def __init__(self, name, variant="default", **kwargs):
            ...
            if variant == "control":
                RETIRED.warn(self, where=name)

A deprecation is declared as a **module constant beside the code that honours
it**, so the sentence an author reads sits next to the branch that triggers it,
and so :func:`declarations` can answer what this version is retiring without
anybody keeping a list.

Where the finding is kept
-------------------------

``validate()`` runs on a flowsheet after layout. A deprecated call happens at
*construction*, often before ``fs.add()``, so at the moment the call is made
there may be no flowsheet in scope to record against. The finding therefore
rides on the object the author is already holding: :meth:`Deprecation.warn`
stores it on that carrier, and :func:`findings` collects from everything the
sheet holds when ``validate()`` finally runs.

That is the shape ``fs.warnings`` and ``fs.route_converged`` already have -- a
fact settled in an earlier phase, parked on an object, and read out by
``validate()`` later. The difference, and the whole reason the carrier is the
unit rather than the sheet, is that those two are settled by ``render()`` and
``route()``, which have a flowsheet in hand by definition. A constructor does
not.

A carrier is the flowsheet itself, or anything the flowsheet holds a list of:
units, streams, loops, components, annotations. That is deliberately not a list
of the classes that happen to have a deprecation today -- there are none yet --
but the general rule "everything an author holds a handle on that this sheet can
reach", so the first customer needs no edit here. A unit built and never added
keeps its finding and is never reported, which is correct: it is not on the
drawing, and ``validate()`` answers for the drawing.

No carrier at all
-----------------

A deprecated free function -- a module-level helper, a classmethod, anything
called with no pandid object in scope -- has nothing to ride on. ``warn()`` with
no carrier files the finding against the *process*, and every ``validate()`` in
that process then reports it.

That is a worse home and the trade is deliberate. Its cost is over-reporting: a
program that builds four sheets and makes one deprecated free call gets the
finding on all four, since nothing ties the call to a sheet. Its alternative is
dropping the finding, which is the exact failure the second signal exists to
prevent -- and a deprecation that reports nowhere is a deprecation nobody acts
on until the release that deletes it. Over-reporting a real defect is the safe
direction, and the noise lasts one release. Pass a carrier wherever one is in
scope; today every deprecation in flight (#136, #138, #154, ``sig_in``/
``sig_out``) has one, because all four are reached through a unit.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pandid.validate import Issue

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet

#: The code every deprecation reports under, beside ``run-off-elevation``,
#: ``gravity-turned`` and the rest. One code for all of them, not one per
#: retired call: the code is what a caller filters on, and "this sheet uses
#: something that is going away" is one thing to filter for. What went and what
#: replaces it is the message's job, which is where the other findings put the
#: part that differs per occurrence too.
CODE = "deprecated"

#: The instance attribute a carrier's findings are kept in. Named only here, so
#: there is no second place a deprecation could be recorded: a carrier does not
#: declare it, and nothing outside this module reads it.
_ATTR = "_deprecations"

#: Findings from calls that had no carrier. Process-wide, and never cleared
#: during a run -- see the module docstring for why that is the lesser evil.
_unattached: list[Issue] = []

#: The flowsheet attributes whose members can carry a finding. Every list a
#: :class:`~pandid.flowsheet.Flowsheet` holds of objects an author built and
#: still has a handle on. ``streams`` is in it even though a stream is minted by
#: ``connect()``: the call that would be deprecated is ``connect()``'s own
#: signature, and the stream it hands back is what the author holds afterwards.
_HELD = ("units", "streams", "loops", "components", "annotations")


@dataclass(frozen=True)
class Deprecation:
    """One retired spelling: what goes, what replaces it, and when it goes.

    Frozen, because a declaration is a fact about a release and not a mutable
    piece of state, and hashable with it, so a caller can put the ones it cares
    about in a set.

    Args:
        what: The call being retired, spelled the way an author types it
            (``"Valve(variant='control')"``). Not a prose description: the
            author has to find this string in their own file.
        instead: The call that replaces it, spelled the same way. Required, and
            required to be a *call*, because a finding that says only "this is
            deprecated" leaves the reader with the same file and no next line to
            type. Every other finding in :mod:`pandid.validate` names the exact
            call that fixes it, and that is why they are worth reading.
        removed_in: The release the old spelling stops working in. Always the
            release after the one it is announced in.
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

        *where* is the thing on the sheet that has to be edited -- a unit tag, a
        stream name -- and is left out when the call named nothing in
        particular. It goes in front, which is where every other finding in
        :mod:`pandid.validate` puts the name of the thing it is about.

        The replacement comes last, so the sentence ends on the line the author
        types next, the way ``run-off-elevation`` ends on the ``pin()`` call and
        ``nozzles-crowded`` on the box that would clear it.
        """
        lead = f"{where}: " if where else ""
        return (f"{lead}{self.what} is deprecated and is removed in pandid "
                f"{self.removed_in}; use {self.instead}")

    def warn(self, carrier: object | None = None, *, where: str = "",
             stacklevel: int = 3) -> None:
        """Emit both signals for one deprecated call.

        The sentence is built once and used twice, which is the whole point: the
        ``DeprecationWarning`` a filter shows and the finding ``validate()``
        reports are the same ``str`` object, so no edit can change one and leave
        the other saying something else.

        *carrier* is the object the finding rides on until ``validate()`` runs:
        the unit under construction, the stream, the flowsheet. ``None`` files it
        against the process instead, for a call with no pandid object in scope;
        the module docstring argues what that costs.

        *stacklevel* defaults to 3 so the warning points at the author's line:
        1 is this method, 2 is the library function that called it, 3 is the
        call that library function was made from. A helper that adds a frame
        between the two passes 4.

        Recorded once per distinct sentence per carrier. A constructor that
        triggers the same deprecation twice on one unit has given the author one
        thing to fix, and saying it twice is saying it twice -- the same
        reasoning ``letter-sequence`` makes one finding per tag with. The
        ``DeprecationWarning`` is still emitted each time, because suppressing a
        repeat is what the ``warnings`` module's own filters are for and they
        are the caller's to set.
        """
        text = self.message(where)
        warnings.warn(text, DeprecationWarning, stacklevel=stacklevel)
        bucket = _unattached if carrier is None else vars(carrier).setdefault(_ATTR, [])
        if not any(seen.message == text for seen in bucket):
            bucket.append(Issue("warning", CODE, text))


def _recorded(obj: object) -> list[Issue]:
    """The findings sitting on one carrier.

    Through ``__dict__`` rather than ``getattr``: the attribute is this module's
    bookkeeping and belongs to the instance, so a class attribute that happened
    to share the name could never be found instead, and
    :meth:`pandid.units.Unit.__getattr__` -- which turns an unknown name into a
    message about the unit's ports -- is a lookup path it has no business going
    down.
    """
    return list(getattr(obj, "__dict__", {}).get(_ATTR, ()))


def findings(fs: "Flowsheet") -> list[Issue]:
    """Every deprecation this sheet triggered, plus every carrier-less one.

    Called by :func:`pandid.validate.validate`, which reports rather than
    recomputes: the findings were built at the deprecated call, which is the only
    moment that knows one was made.
    """
    out = _recorded(fs)
    for held in _HELD:
        for obj in getattr(fs, held, ()):
            out.extend(_recorded(obj))
    out.extend(_unattached)
    return out


def declarations() -> dict[str, Deprecation]:
    """Every deprecation this version declares, keyed by where it is declared.

    Imports each of pandid's own modules and collects the module-level
    :class:`Deprecation` constants in them, which is why the convention is a
    module constant and not one built inline at the call: a declaration nothing
    can enumerate is a declaration that outlives its release quietly.
    ``tests/test_deprecation.py`` is the thing that enumerates them, and holds
    each to a ``removed_in`` that has not shipped yet.

    A constant imported into a second module appears under both names. That is
    the honest answer to "where is this reachable from" and costs the two
    questions this exists for -- what is going away, and is anything overdue --
    nothing.
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


def _forget_unattached() -> None:
    """Drop the carrier-less findings. For tests, which need to start empty.

    Not part of the API: nothing a drawing does should want to un-report a
    deprecation, and a knob for it would be a knob for hiding one.
    """
    _unattached.clear()
