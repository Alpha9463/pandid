"""Declare deprecated API spellings and report them two ways.

A deprecated spelling works for the release that announces it and is
removed in the next (see ``CONTRIBUTING.md``). One :class:`Deprecation`,
declared as a module constant beside the code that honours it, emits:

- a :class:`DeprecationWarning`; and
- a ``deprecated`` finding from :func:`pandid.validate.validate`, since
  Python hides :class:`DeprecationWarning` outside ``__main__`` by
  default.

Both carry the same sentence::

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

The spellings in this example are invented.

A deprecated call often happens before the object is added to a sheet,
so the finding is stored on a carrier: the flowsheet, or a unit, stream,
loop, component or annotation it holds. :func:`findings` collects them
when ``validate()`` runs. A carrier never added to a sheet is never
reported.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pandid.validate import Issue

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet

#: Validation code for every deprecation finding.
CODE = "deprecated"

#: Instance attribute holding a carrier's findings; private to this module.
_ATTR = "_deprecations"

#: Flowsheet lists whose members can carry a finding.
_HELD = ("units", "streams", "loops", "components", "annotations")


@dataclass(frozen=True)
class Deprecation:
    """One deprecated spelling, its replacement and its removal release.

    Frozen, so it is hashable.

    Parameters
    ----------
    what : str
        The deprecated call as an author types it, such as
        ``"Valve(variant='control')"``.
    instead : str
        The replacement call, spelled the same way.
    removed_in : str
        Release in which the old spelling stops working: the one after the
        announcing release.
    note : str, default=""
        What else changes when the replacement is not a drop-in. It is
        printed before the replacement, so the message still ends on the
        call to type.

    Raises
    ------
    ValueError
        If ``what``, ``instead`` or ``removed_in`` is empty.
    """

    what: str
    instead: str
    removed_in: str
    note: str = ""

    def __post_init__(self) -> None:
        """Validate the required fields; ``note`` may be empty."""
        for field, value in (("what", self.what), ("instead", self.instead),
                             ("removed_in", self.removed_in)):
            if not str(value).strip():
                raise ValueError(
                    f"a Deprecation needs a {field}: the finding names the call that "
                    f"is going, the call that replaces it and the release it goes in, "
                    f"and one of the three left empty is a finding nobody can act on"
                )

    def message(self, where: str = "") -> str:
        """Return the sentence both signals carry.

        Parameters
        ----------
        where : str, default=""
            Item to edit, such as a unit tag or stream name; omitted when
            empty.

        Returns
        -------
        str
            ``"<where>: <what> is deprecated and is removed in pandid
            <removed_in>; [<note>, so ]use <instead>"``.
        """
        lead = f"{where}: " if where else ""
        caveat = f"{self.note.rstrip('. ')}, so " if self.note else ""
        return (f"{lead}{self.what} is deprecated and is removed in pandid "
                f"{self.removed_in}; {caveat}use {self.instead}")

    def warn(self, carrier: object, *, where: str = "",
             stacklevel: int = 3) -> None:
        """Emit the warning and record the finding for one deprecated call.

        The same string is used for both. A carrier records each distinct
        sentence once; the warning is emitted every time.

        Parameters
        ----------
        carrier : object
            Object the finding is stored on until ``validate()`` runs: the
            unit being built, the stream or the flowsheet.
        where : str, default=""
            Item to edit, passed to :meth:`message`.
        stacklevel : int, default=3
            Warning stack level. 3 points at the author's call through one
            library frame; a helper adding a frame passes 4.

        Raises
        ------
        TypeError
            If ``carrier`` cannot store attributes.
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
    """Return the findings stored on one carrier.

    Reads ``__dict__`` directly, so a class attribute of the same name is
    ignored and :meth:`pandid.units.Unit.__getattr__` is never called.

    Parameters
    ----------
    obj : object
        Possible carrier.

    Returns
    -------
    list[Issue]
        Stored findings, possibly empty.
    """
    return list(getattr(obj, "__dict__", {}).get(_ATTR, ()))


def findings(fs: "Flowsheet") -> list[Issue]:
    """Return every deprecation finding this sheet's objects carry.

    Parameters
    ----------
    fs : Flowsheet
        Sheet being validated.

    Returns
    -------
    list[Issue]
        Findings on the flowsheet and on the objects it holds.
    """
    out = _recorded(fs)
    for held in _HELD:
        for obj in getattr(fs, held, ()):
            out.extend(_recorded(obj))
    return out


def declarations() -> dict[str, Deprecation]:
    """Return every deprecation this version declares.

    Imports each pandid module and collects its module-level
    :class:`Deprecation` constants. ``tests/test_deprecation.py`` uses this
    to check that no ``removed_in`` release has shipped.

    Returns
    -------
    dict[str, Deprecation]
        Declarations keyed by ``"module.NAME"``. A constant imported into a
        second module appears under both names.
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
