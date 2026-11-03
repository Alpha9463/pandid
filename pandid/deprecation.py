"""Deprecated API spellings, reported as a warning and a finding.

A :class:`Deprecation` is a module constant beside the code that
honours it. :meth:`Deprecation.warn` emits a
:class:`DeprecationWarning` and stores a ``deprecated`` finding on a
carrier; :func:`findings` collects them when ``validate()`` runs.
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

#: Instance attribute holding a carrier's findings.
_ATTR = "_deprecations"

#: Flowsheet lists whose members can carry a finding.
_HELD = ("units", "streams", "loops", "components", "annotations")


@dataclass(frozen=True)
class Deprecation:
    """One deprecated spelling, its replacement and its removal release.

    Parameters
    ----------
    what : str
        The deprecated call, such as ``"Valve(variant='control')"``.
    instead : str
        The replacement call.
    removed_in : str
        Release in which the old spelling stops working.
    note : str, default=""
        What else changes, printed before the replacement.

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
        """Raise if a required field is empty."""
        for field, value in (("what", self.what), ("instead", self.instead),
                             ("removed_in", self.removed_in)):
            if not str(value).strip():
                raise ValueError(
                    f"a Deprecation needs a {field}: the finding names the call that "
                    f"is going, the call that replaces it and the release it goes in, "
                    f"and one of the three left empty is a finding nobody can act on"
                )

    def message(self, where: str = "") -> str:
        """Return the sentence the warning and the finding carry.

        Parameters
        ----------
        where : str, default=""
            Item to edit, such as a unit tag; omitted when empty.

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
        """Emit the warning and record the finding on ``carrier``.

        A carrier records each distinct sentence once.

        Parameters
        ----------
        carrier : object
            Unit, stream or flowsheet the finding is stored on.
        where : str, default=""
            Item to edit, passed to :meth:`message`.
        stacklevel : int, default=3
            Warning stack level; 3 skips one library frame.

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
    """Return the findings stored in one carrier's ``__dict__``."""
    return list(getattr(obj, "__dict__", {}).get(_ATTR, ()))


def findings(fs: "Flowsheet") -> list[Issue]:
    """Return the deprecation findings on a sheet and its objects."""
    out = _recorded(fs)
    for held in _HELD:
        for obj in getattr(fs, held, ()):
            out.extend(_recorded(obj))
    return out


def declarations() -> dict[str, Deprecation]:
    """Return every module-level :class:`Deprecation` in pandid.

    Keys are ``"module.NAME"``; a constant imported into a second module
    appears under both names.
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
