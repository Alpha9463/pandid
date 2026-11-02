"""Check the type of numbers that enter layout through the Python API.

Layout computes with floats and writes numbers with float format specs, so
a coordinate, size or rank must be a real number of a kind both accept:
``int``, ``float`` or a numpy scalar, but not ``bool``, ``Decimal`` (which
cannot be mixed with floats) or ``Fraction`` (which cannot be formatted
with ``:g`` before Python 3.12). :mod:`pandid.spec` uses the same
predicates, so a value the reader refuses is refused at the Python door too.
:func:`suggest` is the "did you mean" hint those refusals share.
"""

from __future__ import annotations

import math
import numbers
from collections.abc import Iterable
from decimal import Decimal
from difflib import get_close_matches
from typing import Any


def is_real(value: Any) -> bool:
    """Return whether a value is a real number layout can compute with.

    Parameters
    ----------
    value : Any
        Value to check.

    Returns
    -------
    bool
        Whether it is a non-bool ``numbers.Real`` that is integral or not
        rational, which excludes ``Fraction`` but keeps numpy floats.
    """
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        return False
    return isinstance(value, numbers.Integral) or not isinstance(value, numbers.Rational)


def is_whole(value: Any) -> bool:
    """Return whether a value is a whole number of any integer type.

    Parameters
    ----------
    value : Any
        Value to check.

    Returns
    -------
    bool
        Whether it is a non-bool ``numbers.Integral``, such as ``int`` or
        ``numpy.int64``.
    """
    return isinstance(value, numbers.Integral) and not isinstance(value, bool)


def suggest(value: str, candidates: Iterable[str]) -> str:
    """Return a ``" (did you mean 'variant'?)"`` hint for a near-miss.

    Parameters
    ----------
    value : str
        Value given.
    candidates : Iterable[str]
        Accepted values.

    Returns
    -------
    str
        Hint, or ``""`` when nothing is close.
    """
    close = get_close_matches(value, candidates, n=1, cutoff=0.6)
    return f" (did you mean {close[0]!r}?)" if close else ""


def _hint(value: Any) -> str:
    """Return advice for a ``Decimal`` or ``Fraction``, the common near misses.

    Parameters
    ----------
    value : Any
        Refused value.

    Returns
    -------
    str
        A sentence to append, or ``""``.
    """
    if isinstance(value, (Decimal, numbers.Rational)) and not isinstance(value, numbers.Integral):
        return "; layout computes with floats, so pass float(value)"
    return ""


def check_real(value: Any, where: str) -> None:
    """Refuse a value that is not a finite real number.

    Parameters
    ----------
    value : Any
        Value to check.
    where : str
        What is being set, for the message, such as ``"P-1: width"``.

    Raises
    ------
    TypeError
        If :func:`is_real` is false.
    ValueError
        If it is NaN or infinite, which has no place on the drawing.
    """
    if not is_real(value):
        raise TypeError(
            f"{where} must be a number (an int or float), got {value!r}{_hint(value)}"
        )
    if not math.isfinite(value):
        raise ValueError(f"{where} must be a finite number, got {value!r}")


def check_whole(value: Any, where: str) -> None:
    """Refuse a value that is not a whole number.

    Parameters
    ----------
    value : Any
        Value to check.
    where : str
        What is being set, for the message, such as ``"P-1: col"``.

    Raises
    ------
    TypeError
        If :func:`is_whole` is false.
    """
    if not is_whole(value):
        raise TypeError(f"{where} must be a whole number (an int), got {value!r}{_hint(value)}")
