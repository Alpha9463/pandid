"""Type checks for numbers entering layout, and the "did you mean" hint.

A real number is an ``int``, ``float`` or numpy integer or float;
``bool``, ``Decimal`` and ``Fraction`` are refused.
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
        Whether it is a non-bool real, integral or not ``Rational``.
    """
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        return False
    return isinstance(value, numbers.Integral) or not isinstance(value, numbers.Rational)


def is_whole(value: Any) -> bool:
    """Return whether a value is a non-bool integer of any type.

    Parameters
    ----------
    value : Any
        Value to check.

    Returns
    -------
    bool
        Whether it is a ``numbers.Integral`` other than ``bool``.
    """
    return isinstance(value, numbers.Integral) and not isinstance(value, bool)


def suggest(value: str, candidates: Iterable[str]) -> str:
    """Return a ``" (did you mean 'variant'?)"`` hint, or ``""``.

    Parameters
    ----------
    value : str
        Value given.
    candidates : Iterable[str]
        Accepted values.

    Returns
    -------
    str
        Hint naming the closest candidate, or ``""``.
    """
    close = get_close_matches(value, candidates, n=1, cutoff=0.6)
    return f" (did you mean {close[0]!r}?)" if close else ""


def _hint(value: Any) -> str:
    """Return advice for a ``Decimal`` or ``Fraction``, or ``""``.

    Parameters
    ----------
    value : Any
        Refused value.

    Returns
    -------
    str
        Text to append to the error message.
    """
    if isinstance(value, (Decimal, numbers.Rational)) and not isinstance(value, numbers.Integral):
        return "; layout computes with floats, so pass float(value)"
    return ""


def check_real(value: Any, where: str) -> None:
    """Raise unless a value is a finite real number.

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
        If it is NaN or infinite.
    """
    if not is_real(value):
        raise TypeError(
            f"{where} must be a number (an int or float), got {value!r}{_hint(value)}"
        )
    if not math.isfinite(value):
        raise ValueError(f"{where} must be a finite number, got {value!r}")


def check_whole(value: Any, where: str) -> None:
    """Raise unless a value is a whole number.

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
        # Advise int() only for an integral Decimal or Fraction.
        exact = (isinstance(value, numbers.Rational) and not isinstance(value, numbers.Integral)
                 and value.denominator == 1
                 or isinstance(value, Decimal) and value.is_finite()
                 and value == value.to_integral_value())
        raise TypeError(f"{where} must be a whole number (an int), got {value!r}"
                        + ("; pass int(value)" if exact else ""))
