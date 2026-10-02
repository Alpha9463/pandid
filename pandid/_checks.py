"""Check the type of numbers that enter layout through the Python API.

Layout computes with floats, so a coordinate, size or rank must be a real
number: any ``numbers.Real`` (``int``, ``float``, numpy scalars,
``Fraction``) but not ``bool``, and not ``Decimal``, which cannot be mixed
with floats. :mod:`pandid.spec` uses the same predicates, so a value the
reader refuses is refused at the Python door too.
"""

from __future__ import annotations

import numbers
from decimal import Decimal
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
        Whether it is a non-bool ``numbers.Real``.
    """
    return isinstance(value, numbers.Real) and not isinstance(value, bool)


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


def _hint(value: Any) -> str:
    """Return advice for a ``Decimal``, which is the common near miss.

    Parameters
    ----------
    value : Any
        Refused value.

    Returns
    -------
    str
        A sentence to append, or ``""``.
    """
    if isinstance(value, Decimal):
        return "; layout computes with floats, so pass float(value)"
    return ""


def check_real(value: Any, where: str) -> None:
    """Refuse a value that is not a real number.

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
    """
    if not is_real(value):
        raise TypeError(
            f"{where} must be a number (an int or float), got {value!r}{_hint(value)}"
        )


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
